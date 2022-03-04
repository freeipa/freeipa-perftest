#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import subprocess as sp
import os
import uuid
import time
import tarfile
import ansible_runner
from datetime import datetime

from ipaperftest.core.constants import (
    ANSIBLE_SERVER_ADD_REPO_PLAYBOOK,
    getLevelName,
    SUCCESS,
    WARNING,
    VAGRANTFILE_TEMPLATE,
    MACHINE_CONFIG_TEMPLATE,
    HOSTS_FILE_TEMPLATE,
    ANSIBLE_CFG_TEMPLATE,
    ANSIBLE_SERVER_CONFIG_PLAYBOOK,
    ANSIBLE_REPLICA_CONFIG_PLAYBOOK,
    ANSIBLE_ENABLE_DATA_COLLECTION_PLAYBOOK,
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
        self.custom_logs = []

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
                    yield Result(self, WARNING, msg="Ran out of IP addresses for private network")

    def run_ansible_playbook_from_template(self, template, filename, playbook_args, ctx):
        """
        The playbook must be passed as a string template.
        It will be written into a file under the sync directory
        using the filename passed.

        Arguments must be passed as a dictionary.
        """

        playbook_str = template.format(**playbook_args)
        playbook_path = "runner_metadata/" + filename + ".yml"
        with open(playbook_path, "w") as f:
            f.write(playbook_str)

        ret = ansible_runner.run(private_data_dir="runner_metadata",
                                 playbook=filename + ".yml",
                                 verbosity=1,
                                 cmdline="--ssh-extra-args '-F vagrant-ssh-config' "
                                         "--flush-cache")

        return ret

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
            sp.run(["systemctl", "restart", "libvirtd"], stdout=sp.PIPE)
            sp.run(["sleep", "5"], stdout=sp.PIPE)

    def reset_sync_folder(self, ctx):
        """Clear up any previously synced data and prepare for new data"""
        sp.run(["rm", "-rf", "sync"], stdout=sp.PIPE)
        sp.run(["mkdir", "sync"], stdout=sp.PIPE)

    def reset_metadata_folder(self, ctx):
        """Clear up metadata from previous executions"""
        sp.run(["rm", "-rf", "runner_metadata"], stdout=sp.PIPE)
        sp.run(["mkdir", "runner_metadata"], stdout=sp.PIPE)

    def validate_vagrantfile(self, ctx):
        """Ensure we have a valid Vagrantfile before proceeding with testing"""
        if sp.run(["vagrant", "validate"], stdout=sp.PIPE).returncode != 0:
            raise RuntimeError("vagrant validate failed")
        else:
            yield Result(self, SUCCESS, msg="Vagrantfile generated and validated successfully.")

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
            cwd="runner_metadata",
            stdout=sp.PIPE,
        )
        with open("runner_metadata/ansible.cfg", "w") as f:
            f.write(ANSIBLE_CFG_TEMPLATE.format(cwd=os.path.join(os.getcwd(), "runner_metadata")))

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
                extra_commands="yum update -y && yum install sysstat -y",
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
                    extra_commands="yum update -y && yum install sysstat -y",
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
        with open("runner_metadata/inventory", "w") as f:
            f.write(inventory_str)

    def generate_ssh_config(self, ctx):
        sp.run("vagrant ssh-config > runner_metadata/vagrant-ssh-config",
               shell=True, stdout=sp.PIPE)

    def ansible_ping(self, ctx):
        print("Sending ping to VMs...")
        ansible_runner.run(private_data_dir="runner_metadata",
                           host_pattern="all",
                           module="ping",
                           cmdline="--ssh-extra-args '-F vagrant-ssh-config'")

        if len(self.hosts.keys()) != len(self.machine_configs):
            yield Result(self, WARNING,
                         msg="Number of hosts provisioned (%s) "
                         "does not match requested amount (%s)" %
                         (len(self.hosts.keys(), len(self.machine_configs))))

    def configure_server(self, ctx):
        if ctx.params["custom_repo_url"]:
            args = {
                "repo_url": ctx.params["custom_repo_url"]
            }
            self.run_ansible_playbook_from_template(ANSIBLE_SERVER_ADD_REPO_PLAYBOOK,
                                                    "add_custom_repo", args, ctx)
        args = {
            "server_ip": self.hosts["server"],
            "domain": self.domain
        }
        self.run_ansible_playbook_from_template(ANSIBLE_SERVER_CONFIG_PLAYBOOK,
                                                "server_config", args, ctx)

    def configure_replicas(self, ctx):
        for host, ip in self.hosts.items():
            if host.startswith("replica"):
                args = {
                    "replica_name": host,
                    "replica_ip": str(ip),
                    "server_ip": self.hosts["server"],
                    "domain": self.domain,
                }
                self.run_ansible_playbook_from_template(ANSIBLE_REPLICA_CONFIG_PLAYBOOK,
                                                        host + "_config", args, ctx)

    def install_server(self, ctx):
        print("Installing IPA server...")
        ansible_runner.run(private_data_dir="runner_metadata",
                           playbook="ansible-freeipa/playbooks/install-server.yml",
                           verbosity=1,
                           cmdline="--ssh-extra-args '-F vagrant-ssh-config' "
                                   "--flush-cache")

    def install_replicas(self, ctx):
        if ctx.params['replicas'] > 0:
            print("Installing IPA replicas...")
            ansible_runner.run(private_data_dir="runner_metadata",
                               playbook="ansible-freeipa/playbooks/install-replica.yml",
                               verbosity=1,
                               cmdline="--ssh-extra-args '-F vagrant-ssh-config' "
                                       "--flush-cache")

    def enable_data_collection(self, ctx):
        print("Starting monitoring on server using SAR...")
        self.run_ansible_playbook_from_template(ANSIBLE_ENABLE_DATA_COLLECTION_PLAYBOOK,
                                                "enable_data_collection", {}, ctx)

    def collect_logs(self, ctx):
        def add_logs(logs):
            for log in logs:
                yield '        - "{}"'.format(log)

        # Wait for sar to analyze system
        print("Waiting before copying logs...")
        time.sleep(60)

        print("Copying logs into sync folder...")
        for host in self.hosts.keys():
            sp.run(["mkdir", "-p", f"sync/{host}"], stdout=sp.PIPE)

        logstr = '\n'.join(add_logs(self.custom_logs))

        args = {
            "cwd": os.getcwd(),
            "custom_logs": logstr
        }
        self.run_ansible_playbook_from_template(ANSIBLE_FETCH_FILES_PLAYBOOK,
                                                "fetch_logs", args, ctx)

    def post_process_logs(self, ctx):
        """Analyze log files for failures, patterns, etc"""
        pass

    def archive_results(self, ctx):
        """ Create tar with logs and metadata"""
        with tarfile.open(self.results_archive_name + ".tar.gz", "w:gz") as tar:
            files_to_add = [
                "sync/",
                "runner_metadata",
                "Vagrantfile"
            ]
            for f in files_to_add:
                tar.add(f)

    def validate_options(self, ctx):
        pass

    def run(self, ctx):
        pass

    def execute(self, ctx):
        funcs = [
            self.validate_options,
            self.cleanup,
            self.generate_vagrantfile,
            self.reset_sync_folder,
            self.reset_metadata_folder,
            self.validate_vagrantfile,
            self.clone_ansible_freeipa,
            self.create_vms,
            self.collect_hosts,
            self.generate_ansibile_inventory,
            self.generate_ssh_config,
            self.ansible_ping,
            self.configure_server,
            self.configure_replicas,
            self.install_server,
            self.install_replicas,
            self.enable_data_collection,
            self.run,
            self.collect_logs,
            self.post_process_logs,
            self.archive_results
        ]

        for func in funcs:
            try:
                yield from func(ctx)
            except TypeError:
                # nothing to yield from in func
                pass


class Result:
    """
    The result of a test.

    :param plugin: The plugin which generated the result.
    :param result: A result constant representing the level of error.
    :param source: If no plugin is passed then the name of the source
                   can be provided directly.
    :param test: If no plugin is passed then the name of the test
                   can be provided directly.
    :param kw: A dictionary of items providing insight in the error.

    Either both test and source need to be provided or plugin needs
    to be provided.

    kw is meant to provide some level of flexibility to test authors
    but the following is a set of pre-defined keys that may be present:

        key: some test can have multiple tests. This
             provides for uniqueuess.
        msg: A message that can take other keywords as input
        exception: used when a test raises an exception
    """
    def __init__(self, plugin, result, source=None, test=None,
                 start=None, duration=None, when=None, **kw):
        self.result = result
        self.kw = kw
        self.when = when
        self.duration = duration
        self.uuid = str(uuid.uuid4())
        if None not in (test, source):
            self.test = test
            self.source = source
        else:
            if plugin is None:
                raise TypeError('source and test or plugin must be provided')
            self.test = plugin.__class__.__name__
            self.source = plugin.__class__.__module__
        if start is not None:
            dur = datetime.utcnow() - start
            self.duration = '%6.6f' % dur.total_seconds()

        assert getLevelName(result) is not None

    def __repr__(self):
        return "%s.%s(%s): %s" % (self.source, self.test, self.kw,
                                  self.result)


class Results:
    """
    A list-like collection of Result values.

    Provides a very limited subset of list operations. Is intended for
    internal-use only and not by test functions.

    Usage::

        results = Results()

        result = Result(plugin, SUCCESS, **kw)
        results.add(result)
    """
    def __init__(self):
        self.results = []

    def __len__(self):
        return len(self.results)

    def add(self, result):
        assert isinstance(result, Result)
        self.results.append(result)

    def extend(self, results):
        assert isinstance(results, Results)
        self.results.extend(results.results)

    def output(self):
        for result in self.results:
            yield dict(source=result.source,
                       test=result.test,
                       result=getLevelName(result.result),
                       uuid=result.uuid,
                       when=result.when,
                       duration=result.duration,
                       kw=result.kw)
