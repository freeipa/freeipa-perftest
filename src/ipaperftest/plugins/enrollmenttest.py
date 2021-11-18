#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import subprocess as sp
import time

from ipaperftest.core.main import Plugin
from ipaperftest.core.constants import MACHINE_CONFIG_TEMPLATE
from ipaperftest.plugins.registry import registry


@registry
class EnrollmentTest(Plugin):

    def generate_clients(self, ctx):
        for i in range(ctx.params['amount']):
            idx = str(i).zfill(3)
            machine_name = "client{}".format(idx)
            yield(
                MACHINE_CONFIG_TEMPLATE.format(
                    machine_name=machine_name,
                    box=ctx.params['client_image'],
                    hostname=machine_name + "." + self.domain.lower(),
                    memory_size=384,
                    cpus_number=1,
                    extra_commands="",
                    ip=next(self.ip_generator),
                )
            )

    def run(self, ctx):
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

        return
