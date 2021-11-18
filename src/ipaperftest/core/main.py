#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import click
import os
import pkg_resources
import subprocess as sp
import sys
import time

from ipaperftest.core.constants import (
    VAGRANTFILE_TEMPLATE,
    MACHINE_CONFIG_TEMPLATE,
    HOSTS_FILE_TEMPLATE,
    ANSIBLE_CFG_TEMPLATE,
    ANSIBLE_FETCH_FILES_PLAYBOOK,
)


class Registry:
    """
    A decorator that makes plugins available to the API

    Usage::

        register = Registry()

        @register()
        class some_plugin(...):
            ...
    """
    def __init__(self):
        self.plugins = []

    def __call__(self, cls):
        if not callable(cls):
            raise TypeError('plugin must be callable; got %r' % cls)
        self.plugins.append(cls)
        return cls

    def get_plugins(self):
        for plugincls in self.plugins:
            yield plugincls(self)


class Plugin:
    """
    Base class for all plugins.

    registry defines where the plugin was registered, normally via
    a pkg_resource.

    Usage::

        register = Registry()

        @register()
        test_foo(Plugin)
            def run(self):
               ...

    """
    def __init__(self, registry):
        self.registry = registry
        self.domain = "ipa.test"
        self.ip_generator = self.generate_ip()
        self.machine_configs = []
        self.hosts = dict()

    # IPs will be like 192.168.x.y
    def generate_ip(self):
        ip_x = 3
        ip_y = 2

        while True:
            yield "192.168.{}.{}".format(ip_x, ip_y)
            ip_y += 1
            if ip_y == 255:
                ip_y = 2
                ip_x += 1
                if ip_x == 256:
                    print("WARNING: Ran out of IP addresses for private network!")

    def generate_clients(self, ctx):
        # A generator to yield client configurations which will be
        # appended to the list of machine configs.
        yield None

    def cleanup(self, ctx):
        """We clean up *before* an execution so that the VMs remain

           This is so we can evaluate what, if anything, went wrong.
        """
        print("Destroying previous VMs...")
        if os.path.exists("Vagrantfile"):
            sp.run(["vagrant", "destroy", "-f"], stdout=sp.PIPE)

    def reset_sync_folder(self, ctx):
        """Clear up any previously synced data and prepare for new data"""
        sp.run(["rm", "-rf", "sync"], stdout=sp.PIPE)
        sp.run(["mkdir", "sync"], stdout=sp.PIPE)

    def validate_vagrantfile(self, ctx):
        """Ensure we have a valid Vagrantfile before proceeding with testing"""
        if sp.run(["vagrant", "validate"], stdout=sp.PIPE).returncode != 0:
            raise RuntimeError("vagrant validate failed")
        else:
            print("Vagrantfile generated and validated succesfully.")

    def clone_ansible_freeipa(self, ctx):
        """ Clone ansible-freeipa upstream and create the Ansible config"""
        sp.run(
            [
                "git",
                "clone",
                "--depth=1",
                "--branch",
                "v0.3.8",
                "https://github.com/freeipa/ansible-freeipa.git",
            ],
            stdout=sp.PIPE,
        )
        with open("ansible.cfg", "w") as f:
            f.write(ANSIBLE_CFG_TEMPLATE.format(cwd=os.getcwd()))

    def generate_vagrantfile(self, ctx):
        """Create the Vagrantfile

           This directly controls creating the entries for the server
           and replicas. A per-test generator is used to generate the
           client entries.
        """
        # Initial server
        self.machine_configs = [
            MACHINE_CONFIG_TEMPLATE.format(
                machine_name="server",
                box=ctx.params['server_image'],
                hostname="server." + self.domain.lower(),
                memory_size=8192,
                cpus_number=4,
                extra_commands="yum install sysstat -y",
                ip=next(self.ip_generator),
            )
        ]

        # Replicas
        for i in range(ctx.params['replicas']):
            name = "replica{}".format(str(i))
            self.machine_configs.append(
                MACHINE_CONFIG_TEMPLATE.format(
                    machine_name=name,
                    box=ctx.params['server_image'],
                    hostname=name + "." + self.domain.lower(),
                    memory_size=8192,
                    cpus_number=4,
                    extra_commands="yum install sysstat -y",
                    ip=next(self.ip_generator),
                )
            )

        # A plugin would here extend this list as needed
        for conf in self.generate_clients(ctx):
            if conf:
                self.machine_configs.append(conf)

        # Related: https://github.com/hashicorp/vagrant/issues/4967
        vagrant_additional_config = (
            "config.ssh.insert_key = false\n"
            'config.ssh.private_key_path = ["~/.vagrant.d/insecure_private_key", "%s"]'
            % ctx.params['private_key']
            if ctx.params.get('private_key')
            else ""
        )

        file_contents = VAGRANTFILE_TEMPLATE.format(
            vagrant_additional_config=vagrant_additional_config,
            machine_configs="\n".join(self.machine_configs),
        )
        with open("Vagrantfile", "w") as f:
            f.write(file_contents)

    def create_vms(self, ctx):
        """Bring up all the configured virtual machines"""
        print("Creating VMs...")
        sp.run(["vagrant", "up", "--parallel"])

    def collect_hosts(self, ctx):
        """Collect IP information on the configured hosts in a dict

           hostname:ip
        """
        grep_output = sp.run(
            "vagrant ssh-config | grep -i HostName -B 1",
            shell=True, stdout=sp.PIPE).stdout.decode("utf-8")
        host_lines = grep_output.split("--")
        for line in host_lines:
            pair = line.replace("\n", "").replace("Host ", "").split("  HostName ")
            self.hosts[pair[0]] = pair[1]

    def generate_ansibile_inventory(self, ctx):
        # Each replica should have main server + all the other replicas
        # as servers so the topology is built correctly
        replica_lines = []
        for name, _ in self.hosts.items():
            if name.startswith("client") or name.startswith("server"):
                continue
            servers = ["server." + self.domain]
            for other, _ in self.hosts.items():
                if other.startswith("replica") and other != name:
                    servers.append(other + "." + self.domain)
            replica_lines.append(name + " ipareplica_servers={}".format(",".join(servers)))

        inventory_str = HOSTS_FILE_TEMPLATE.format(
            domain=self.domain.lower(),
            realm=self.domain.upper(),
            client_hostnames="\n".join(
                [name for name, _ in self.hosts.items() if name.startswith("client")]
            ),
            replica_hostnames="\n".join(replica_lines),
        )
        with open("hosts", "w") as f:
            f.write(inventory_str)

    def generate_ssh_config(self, ctx):
        sp.run("vagrant ssh-config > vagrant-ssh-config",
               shell=True, stdout=sp.PIPE)

    def ansible_ping(self, ctx):
        print("Sending ping to VMs...")
        sp.run(
            "ansible -i hosts all -m ping --ssh-extra-args '-F vagrant-ssh-config'",
            shell=True,
        )

        if len(self.hosts.keys()) != len(self.machine_configs):
            print(
                "WARNING: number of hosts provisioned ({}) does not match "
                "requested amount ({}).".format(
                    len(self.hosts.keys()), len(self.machine_configs)
                )
            )

    def configure_server(self, ctx):
        server_cmds = [
            "sudo sysctl -w net.ipv6.conf.all.disable_ipv6=0",
            r"sudo sed -i 's/127.*.*.*\s*server/{} server.{} server/' "
            "/etc/hosts".format(self.hosts["server"], self.domain),
        ]
        sp.run(
            'vagrant ssh server -c "{}"'.format(" && ".join(server_cmds)),
            shell=True,
            stdout=sp.PIPE,
            stderr=sp.PIPE,
        )

    def configure_replicas(self, ctx):
        for host, ip in self.hosts.items():
            if host.startswith("replica"):
                replica_cmds = [
                    "{{ echo '{} server.{} server' | "
                    "sudo tee -a /etc/hosts; }}".format(
                        self.hosts["server"], self.domain
                    ),
                    "sudo rm -f /etc/resolv.conf",
                    "{{ echo 'nameserver {server}' | "
                    "sudo tee -a /etc/resolv.conf; }}".format(
                        server=self.hosts["server"]
                    ),
                    r"sudo sed -i '/127.*.*.*\s*replica*/d' /etc/hosts",
                    "{{ echo '{} {} {}' | sudo tee -a /etc/hosts; }}".format(
                        ip, host + "." + self.domain, host
                    )
                ]
                sp.run(
                    'vagrant ssh {} -c "{}"'.format(host, " && ".join(replica_cmds)),
                    shell=True,
                    stdout=sp.PIPE,
                    stderr=sp.PIPE,
                )

    def install_server(self, ctx):
        print("Installing IPA server...")
        sp.run(
            "ansible-playbook -v -i hosts "
            "ansible-freeipa/playbooks/install-server.yml "
            "--ssh-extra-args '-F vagrant-ssh-config'",
            shell=True,
        )

    def install_replicas(self, ctx):
        if ctx.params['replicas'] > 0:
            sp.run(
                "ansible-playbook -v -i hosts "
                "ansible-freeipa/playbooks/install-replica.yml "
                "--ssh-extra-args '-F vagrant-ssh-config'",
                shell=True,
            )

    def enable_data_collection(self, ctx):
        print("Starting monitoring on server using SAR...")
        sar_cmd = "nohup sar -o ~/saroutput 2 >/dev/null 2>&1 &"
        sp.run(
            'vagrant ssh server -c "{}"'.format(sar_cmd),
            shell=True,
            stdout=sp.DEVNULL,
            stdin=sp.DEVNULL,
            stderr=sp.DEVNULL,
        )

    def collect_logs(self, ctx):
        # Wait for sar to analyze system
        print("Waiting before copying logs...")
        time.sleep(60)

        print("Copying logs into sync folder...")
        for host in self.hosts.keys():
            sp.run(["mkdir", "-p", f"sync/{host}"], stdout=sp.PIPE)

        with open("fetch_logs.yml", "w") as ansible_fetch_file:
            ansible_fetch_file.write(
                ANSIBLE_FETCH_FILES_PLAYBOOK.format(cwd=os.getcwd())
            )
        sp.run(
            "ansible-playbook -v -i hosts fetch_logs.yml --ssh-extra-args '-F vagrant-ssh-config'",
            shell=True,
            stdout=sp.PIPE,
        )

    def post_process_logs(self, ctx):
        """Analyze log files for failures, patterns, etc"""
        pass

    def validate_options(self, ctx):
        pass

    def run(self, ctx):
        pass

    def execute(self, ctx):
        self.validate_options(ctx)
        self.cleanup(ctx)
        self.generate_vagrantfile(ctx)
        self.reset_sync_folder(ctx)
        self.validate_vagrantfile(ctx)
        self.clone_ansible_freeipa(ctx)
        self.create_vms(ctx)
        self.collect_hosts(ctx)
        self.generate_ansibile_inventory(ctx)
        self.generate_ssh_config(ctx)
        self.ansible_ping(ctx)
        self.configure_server(ctx)
        self.configure_replicas(ctx)
        self.install_server(ctx)
        self.install_replicas(ctx)
        self.enable_data_collection(ctx)
        self.run(ctx)
        self.collect_logs(ctx)
        self.post_process_logs(ctx)


def find_registries(entry_points):
    registries = {}
    for entry_point in entry_points:
        registries.update({
            ep.name: ep.resolve()
            for ep in pkg_resources.iter_entry_points(entry_point)
        })
    return registries


def find_plugins(name, registry):
    for ep in pkg_resources.iter_entry_points(name):
        # load module
        ep.load()
    return registry.get_plugins()


class RunTest:
    def __init__(self, entry_points):
        """Initialize class variables

          entry_points: A list of entry points to find plugins
        """
        self.entry_points = entry_points

    def run(self, ctx):
        plugins = []

        for name, registry in find_registries(self.entry_points).items():
            registry.initialize()
            for plugin in find_plugins(name, registry):
                plugins.append(plugin)

        # TODO: short-circuit this and run directly above. Easier to
        #       troubleshoot here
        for plugin in plugins:
            if plugin.__class__.__name__ == ctx.params['test']:
                plugin.execute(ctx)


@click.command("cli", context_settings={"show_default": True})
@click.option("--test", default="EnrollmentTest", help="Test to execute.")
@click.option(
    "--client-image",
    default="antorres/fedora-34-ipa-client",
    help="Vagrant image to use for clients.",
)
@click.option(
    "--server-image",
    default="antorres/fedora-34-ipa-client",
    help="Vagrant image to use for server.",
)
@click.option("--amount", default=1, help="Size of the test.")
@click.option(
    "--replicas",
    default=0,
    type=click.IntRange(0, 2),
    help="Number of replicas to create.",
)
@click.option("--command", help="Command to execute during APITest.")
@click.option(
    "--private-key",
    help="Private key needed to access VMs in case the Vagrant default is not enough.",
)
@click.pass_context
def main(
    ctx,
    test,
    command,
    private_key,
    client_image="antorres/fedora-34-ipa-client",
    server_image="antorres/fedora-34-ipa-client",
    amount=1,
    replicas=0,
):

    tests = RunTest(['ipaperftest.registry'])
    try:
        tests.run(ctx)
    except RuntimeError:
        sys.exit(1)
