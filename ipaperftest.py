#!/usr/bin/env python3

#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import subprocess as sp
import click
import time
import os
import math

VAGRANTFILE_TEMPLATE = """
    Vagrant.configure("2") do |config|
        config.vm.synced_folder ".", "/vagrant", disabled: true
        config.vm.provider :libvirt do |libvirt|
            # Disabling QEMU Session as it causes issues with private network
            # https://fedoraproject.org/wiki/Changes/Vagrant_2.2_with_QEMU_Session
            libvirt.qemu_use_session = false
            libvirt.management_network_address = "192.168.0.0/16"
        end
        {vagrant_additional_config}
        {machine_configs}
    end
"""

MACHINE_CONFIG_TEMPLATE = """
    config.vm.define :{machine_name} do |{machine_name}|
        {machine_name}.vm.provider "libvirt" do |v|
            v.memory = {memory_size}
            v.cpus = {cpus_number}
        end
        {machine_name}.vm.box = "{box}"
        {machine_name}.vm.hostname = "{hostname}"
        {machine_name}.vm.network "private_network", libvirt__netmask: "255.255.0.0", ip: "{ip}"
        {machine_name}.vm.provision "shell", inline: <<-SHELL
            {extra_commands}
        SHELL
    end
"""

HOSTS_FILE_TEMPLATE = """
[ipaserver]
server

[ipaserver:vars]
ipaadmin_password=password
ipadm_password=password
ipaserver_domain={domain}
ipaserver_realm={realm}
ipaserver_setup_dns=yes
ipaserver_no_forwarders=yes
ipaserver_auto_reverse=yes

[ipareplicas]
{replica_hostnames}

[ipareplicas:vars]
ipaadmin_password=password
ipadm_password=password
ipareplica_domain={domain}
ipaserver_realm={realm}
ipareplica_setup_dns=yes
ipareplica_no_forwarders=yes
ipareplica_auto_reverse=yes

[ipaclients]
{client_hostnames}

[ipaclients:vars]
ipaadmin_password=password
ipaserver_domain={domain}
ipaserver_realm={realm}
"""

ANSIBLE_CFG_TEMPLATE = """
[defaults]
deprecation_warnings=False
roles_path   = {cwd}/ansible-freeipa/roles
library      = {cwd}/ansible-freeipa/plugins/modules
module_utils = {cwd}/ansible-freeipa/plugins/module_utils
"""

ANSIBLE_FETCH_FILES_PLAYBOOK = """
---
- name: Fetch IPA server log files
  hosts: ipaserver
  become: true
  tasks:
    - synchronize:
        src: "{{{{ item }}}}"
        dest: "{cwd}/sync/{{{{ ansible_hostname }}}}/"
        mode: pull
        use_ssh_args: yes
      with_items:
        - "/var/log/ipaserver-install.log"
        - "/var/log/ipaclient-install.log"
        - "/var/log/httpd"
        - "/var/log/dirsrv"
        - "/var/log/krb5kdc.log"
        - "/var/log/pki/pki-tomcat/ca"
        - "~/saroutput"

- name: Fetch IPA clients log files
  hosts: ipaclients
  become: true
  tasks:
    - synchronize:
        src: "{{{{ item }}}}"
        dest: "{cwd}/sync/{{{{ ansible_hostname }}}}/"
        mode: pull
        use_ssh_args: yes
      with_items:
        - "/var/log/ipaclient-install.log"

"""


class EnrollmentTest:
    # Simultaneous client enrollment test.

    def __init__(self, hosts):
        # hosts: hostname:ip dict
        self.hosts = hosts

    def run(self):
        # Client installations will be triggered at now + 1min per 30 clients
        client_install_time = (
            int(time.time()) + max(int(len(self.hosts.keys()) / 30), 1) * 60
        )

        client_cmds = [
            "sudo rm -f /etc/resolv.conf",
            "{{ echo 'nameserver {server}' | sudo tee -a /etc/resolv.conf; }}".format(
                server=self.hosts["server"]
            ),
            "sleep $(( {} - $(date +%s) ))".format(str(client_install_time)),
            "sudo ipa-client-install -p admin -w password -U "
            "--enable-dns-updates --no-nisdomain -N",
        ]

        processes = {}
        non_client_hosts = 0
        for host in self.hosts.keys():
            if host == "server" or host.startswith("replica"):
                non_client_hosts += 1
                continue
            proc = sp.Popen(
                'vagrant ssh {host} -c "{cmd}"'.format(
                    host=host, cmd=" && ".join(client_cmds)
                ),
                shell=True,
                stdout=sp.DEVNULL,
                stdin=sp.DEVNULL,
                stderr=sp.DEVNULL,
            )
            processes[host] = proc
        print(
            "Client installation commands sent, client install will start at %s"
            % time.ctime(client_install_time)
        )

        print("Waiting for client installs to be completed...")
        self.clients_succeeded = 0
        clients_returncodes = ""
        for host, proc in processes.items():
            proc.communicate()
            returncode = proc.returncode
            rc_str = "Host " + host + " returned " + str(returncode)
            clients_returncodes += rc_str + "\n"
            print(rc_str)
            if returncode == 0:
                self.clients_succeeded += 1
        print("Clients succeeded: %s" % str(self.clients_succeeded))
        print("Return codes written to sync directory.")
        with open("sync/returncodes", "w") as f:
            f.write(clients_returncodes)

        # Check all hosts have been registered in server
        kinit_cmd = "echo password | kinit admin"
        host_find_cmd = "ipa host-find --sizelimit=0 | grep 'Host name:' | wc -l"
        sp.run(
            'vagrant ssh server -c "{}"'.format(kinit_cmd),
            shell=True,
            stdout=sp.PIPE,
            stderr=sp.PIPE,
        )
        host_find_output = (
            sp.run(
                'vagrant ssh server -c "{}"'.format(host_find_cmd),
                shell=True,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
            )
            .stdout.decode("utf-8")
            .strip()
        )
        try:
            if (
                int(host_find_output) == self.clients_succeeded + non_client_hosts
                and len(self.hosts.keys()) == self.clients_succeeded + non_client_hosts
            ):
                print("All clients enrolled succesfully.")
            else:
                print(
                    "ERROR: client installs succeeded number does not match "
                    "host-find output. Check for failures during installation."
                )
                print("Hosts found in host-find: %s" % str(host_find_output))
                print(
                    "Hosts that returned 0 during install: %s" % self.clients_succeeded
                )
        except ValueError:
            print(
                "Failed converting IPA host-find output to int. Value was: %s"
                % host_find_output
            )


class APITest:
    def __init__(self, cmd, amount, hosts):
        self.base_cmd = cmd
        self.amount = amount
        self.hosts = hosts

    def run(self):
        # Deploy clients
        print("Deploying clients...")
        clients = [name for name, ip in self.hosts.items() if name.startswith("client")]
        client_cmds = [
            "sudo rm -f /etc/resolv.conf",
            "{{ echo 'nameserver {server}' | sudo tee -a /etc/resolv.conf; }}".format(
                server=self.hosts["server"]
            ),
            "sudo ipa-client-install -p admin -w password -U "
            "--enable-dns-updates --no-nisdomain -N",
            "{ echo password | kinit admin; }",
        ]
        for client in clients:
            sp.run(
                'vagrant ssh {} -c "{}"'.format(client, " && ".join(client_cmds)),
                shell=True,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
            )

        # Wait 2 min per client before running the commands
        local_run_time = (
            sp.run(
                "vagrant ssh server -c 'date --date now+{}min +%H:%M'".format(
                    str(len(clients) * 2)
                ),
                shell=True,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
            )
            .stdout.decode("utf-8")
            .strip()
        )

        for i in range(self.amount):
            client_idx = math.floor(i / 50)
            formated_api_cmd = self.base_cmd.format(id=str(i))
            cmd = (
                r"echo 'echo {cmd} > ~/command{id}log; {cmd} >> "
                r"~/command{id}log 2>&1; echo \$? >> ~/command{id}log' "
                r"| at {time}".format(
                 cmd=formated_api_cmd, id=str(i), time=local_run_time)
            )
            sp.run(
                'vagrant ssh {} -c "{}"'.format(clients[client_idx], cmd),
                shell=True,
                stdin=sp.DEVNULL,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
            )

        print("Commands will be run at %s (machine local time)" % local_run_time)
        # Wait until all atd commands have completed
        # (that is, once /var/spool/at only has the 'spool' dir)
        while True:
            clients_cmds_pending = []
            for client in clients:
                cmds_pending = (
                    sp.run(
                        "vagrant ssh {} -c 'sudo ls /var/spool/at | wc -l'".format(
                            client
                        ),
                        shell=True,
                        stdout=sp.PIPE,
                        stderr=sp.PIPE,
                    )
                    .stdout.decode("utf-8")
                    .strip()
                )
                clients_cmds_pending.append(cmds_pending)
            if all([cmds == "1" for cmds in clients_cmds_pending]):
                break
            time.sleep(5)

        commands_succeeded = 0
        returncodes = ""
        for i in range(self.amount):
            client_idx = math.floor(i / 50)
            file_lines = (
                sp.run(
                    "vagrant ssh {host} -c 'cat ~/command{id}log'".format(
                        host=clients[client_idx], id=str(i)
                    ),
                    shell=True,
                    stdout=sp.PIPE,
                    stderr=sp.PIPE,
                )
                .stdout.decode("utf-8")
                .splitlines()
            )
            rc_str = "Command '{}' returned {}".format(file_lines[0], file_lines[-1])
            returncodes += rc_str + "\n"
            print(rc_str)
            if file_lines[-1] == "0":
                commands_succeeded += 1
            with open("sync/command{}log".format(str(i)), "w") as f:
                f.writelines("\n".join(file_lines))
        print("Return codes written to sync directory.")
        with open("sync/returncodes", "w") as f:
            f.write(returncodes)

        if commands_succeeded == self.amount:
            print("All commands executed succesfully.")
        else:
            print("ERROR: not all commands completed succesfully. Check logs.")


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
def main(
    test,
    command,
    private_key,
    client_image="antorres/fedora-34-ipa-client",
    server_image="antorres/fedora-34-ipa-client",
    amount=1,
    replicas=0,
):

    # Destroy previous VMs
    print("Destroying previous VMs...")
    sp.run(["vagrant", "destroy", "-f"], stdout=sp.PIPE)

    domain = "ipa.test"

    # IPs will be like 192.168.x.y
    def generate_ip():
        ip_x = 0
        ip_y = 2

        while True:
            yield "192.168.{}.{}".format(ip_x, ip_y)
            ip_y += 1
            if ip_y == 255:
                ip_y = 2
                ip_x += 1
                if ip_x == 256:
                    print("WARNING: Ran out of IP addresses for private network!")

    ip_generator = generate_ip()

    # Generate Vagrantfile
    machine_configs = [
        MACHINE_CONFIG_TEMPLATE.format(
            machine_name="server",
            box=server_image,
            hostname="server." + domain.lower(),
            memory_size=8192,
            cpus_number=4,
            extra_commands="yum install sysstat -y",
            ip=next(ip_generator),
        )
    ]

    # Add replicas to Vagrantfile
    for i in range(replicas):
        name = "replica{}".format(str(i))
        machine_configs.append(
            MACHINE_CONFIG_TEMPLATE.format(
                machine_name=name,
                box=server_image,
                hostname=name + "." + domain.lower(),
                memory_size=8192,
                cpus_number=4,
                extra_commands="yum install sysstat -y",
                ip=next(ip_generator),
            )
        )

    if test == "EnrollmentTest":
        # Enrollment test needs client machines
        for i in range(amount):
            idx = str(i).zfill(3)
            machine_name = "client{}".format(idx)
            machine_configs.append(
                MACHINE_CONFIG_TEMPLATE.format(
                    machine_name=machine_name,
                    box=client_image,
                    hostname=machine_name + "." + domain.lower(),
                    memory_size=384,
                    cpus_number=1,
                    extra_commands="",
                    ip=next(ip_generator),
                )
            )
    elif test == "APITest":
        if not command:
            print("Please specify a command to run using the --command option.")
            return
        # Use a separate client for each 50 commands
        n_clients = math.ceil(amount / 50)
        for i in range(n_clients):
            machine_name = "client{}".format(str(i).zfill(3))
            machine_configs.append(
                MACHINE_CONFIG_TEMPLATE.format(
                    machine_name=machine_name,
                    box=client_image,
                    hostname=machine_name + "." + domain.lower(),
                    memory_size=4098,
                    cpus_number=2,
                    extra_commands="",
                    ip=next(ip_generator),
                )
            )
    else:
        print("Selected test '%s' couldn't be found." % test)
        return

    # Related: https://github.com/hashicorp/vagrant/issues/4967
    vagrant_additional_config = (
        "config.ssh.insert_key = false\n"
        'config.ssh.private_key_path = ["~/.vagrant.d/insecure_private_key", "%s"]'
        % private_key
        if private_key
        else ""
    )
    file_contents = VAGRANTFILE_TEMPLATE.format(
        vagrant_additional_config=vagrant_additional_config,
        machine_configs="\n".join(machine_configs),
    )
    with open("Vagrantfile", "w") as f:
        f.write(file_contents)

    # Clear sync folder
    sp.run(["rm", "-rf", "sync"], stdout=sp.PIPE)
    sp.run(["mkdir", "sync"], stdout=sp.PIPE)
    # Validate Vagrantfile
    if sp.run(["vagrant", "validate"], stdout=sp.PIPE).returncode != 0:
        return
    else:
        print("Vagrantfile generated and validated succesfully.")

    # Clone ansible-freeipa and create ansible config
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

    # Run Vagrantfile
    print("Creating VMs...")
    sp.run(["vagrant", "up", "--parallel"])

    # Gather info about hosts (dict hostname:ip)
    hosts = {}
    grep_output = sp.run(
        "vagrant ssh-config | grep -i HostName -B 1", shell=True, stdout=sp.PIPE
    ).stdout.decode("utf-8")
    host_lines = grep_output.split("--")
    for line in host_lines:
        pair = line.replace("\n", "").replace("Host ", "").split("  HostName ")
        hosts[pair[0]] = pair[1]

    # Each replica should have main server + all the other replicas as servers
    replica_lines = []
    for name, _ in hosts.items():
        if name.startswith("client") or name.startswith("server"):
            continue
        servers = ["server." + domain]
        for other, _ in hosts.items():
            if other.startswith("replica") and other != name:
                servers.append(other + "." + domain)
        replica_lines.append(name + " ipareplica_servers={}".format(",".join(servers)))

    # Generate ansible inventory file
    inventory_str = HOSTS_FILE_TEMPLATE.format(
        domain=domain.lower(),
        realm=domain.upper(),
        client_hostnames="\n".join(
            [name for name, _ in hosts.items() if name.startswith("client")]
        ),
        replica_hostnames="\n".join(replica_lines),
    )
    with open("hosts", "w") as f:
        f.write(inventory_str)

    # Generate SSH config file
    sp.run("vagrant ssh-config > vagrant-ssh-config", shell=True, stdout=sp.PIPE)

    # Ping through ansible
    print("Sending ping to VMs...")
    sp.run(
        "ansible -i hosts all -m ping --ssh-extra-args '-F vagrant-ssh-config'",
        shell=True,
    )

    if len(hosts.keys()) != len(machine_configs):
        print(
            "WARNING: number of hosts provisioned ({}) does not match"
            "requested amount ({}).".format(
                len(hosts.keys()), len(machine_configs)
            )
        )

    # Initial server config
    server_cmds = [
        "sudo sed -i 's/disable_ipv6 = 1/disable_ipv6 = 0/' /etc/sysctl.conf",
        "sudo sysctl -p",
        r"sudo sed -i 's/127.*.*.*\s*server/{} server.{} server/' /etc/hosts".format(
            hosts["server"], domain
        ),
    ]
    sp.run(
        'vagrant ssh server -c "{}"'.format(" && ".join(server_cmds)),
        shell=True,
        stdout=sp.PIPE,
        stderr=sp.PIPE,
    )

    # Replica config
    replica_cmds = [
        "{{ echo '{} server.{} server' | sudo tee -a /etc/hosts; }}".format(
            hosts["server"], domain
        ),
        "sudo rm -f /etc/resolv.conf",
        "{{ echo 'nameserver {server}' | sudo tee -a /etc/resolv.conf; }}".format(
            server=hosts["server"]
        ),
        r"sudo sed -i '/127.*.*.*\s*replica*/d' /etc/hosts",
    ]

    for host, ip in hosts.items():
        if host.startswith("replica"):
            sp.run(
                'vagrant ssh {} -c "{}"'.format(host, " && ".join(replica_cmds)),
                shell=True,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
            )

    # Install ipaserver
    print("Installing IPA server...")
    sp.run(
        "ansible-playbook -v -i hosts "
        "ansible-freeipa/playbooks/install-server.yml "
        "--ssh-extra-args '-F vagrant-ssh-config'",
        shell=True,
    )

    # Install replicas
    if replicas > 0:
        sp.run(
            "ansible-playbook -v -i hosts "
            "ansible-freeipa/playbooks/install-replica.yml "
            "--ssh-extra-args '-F vagrant-ssh-config'",
            shell=True,
        )

    # Start SAR on server
    print("Starting monitoring on server using SAR...")
    sar_cmd = "nohup sar -o ~/saroutput 2 >/dev/null 2>&1 &"
    sp.run(
        'vagrant ssh server -c "{}"'.format(sar_cmd),
        shell=True,
        stdout=sp.DEVNULL,
        stdin=sp.DEVNULL,
        stderr=sp.DEVNULL,
    )

    # Setup and launch selected test
    if test == "EnrollmentTest":
        selected_test = EnrollmentTest(hosts)
    elif test == "APITest":
        selected_test = APITest(command, amount, hosts)

    selected_test.run()

    # Wait for sar to analyze system
    print("Waiting before copying logs...")
    time.sleep(60)

    print("Copying logs into sync folder...")
    for host in hosts.keys():
        sp.run(["mkdir", "-p", f"sync/{host}"], stdout=sp.PIPE)
    with open("fetch_logs.yml", "w") as ansible_fetch_file:
        ansible_fetch_file.write(ANSIBLE_FETCH_FILES_PLAYBOOK.format(cwd=os.getcwd()))
    sp.run(
        "ansible-playbook -v -i hosts fetch_logs.yml --ssh-extra-args '-F vagrant-ssh-config'",
        shell=True,
        stdout=sp.PIPE,
    )


if __name__ == "__main__":
    main()
