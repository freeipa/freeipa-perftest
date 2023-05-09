#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import time
import os
from datetime import datetime

from ipaperftest.core.plugin import Plugin, Result
from ipaperftest.core.constants import (
    SUCCESS,
    WARNING,
    ERROR,
    ANSIBLE_ENROLLMENTTEST_CLIENT_CONFIG_PLAYBOOK,
    ANSIBLE_COUNT_IPA_HOSTS_PLAYBOOK)
from ipaperftest.plugins.registry import registry


@registry
class EnrollmentTest(Plugin):

    def __init__(self, registry):
        super().__init__(registry)
        self.custom_logs = ["install-cmd-output", ]

    def generate_clients(self, ctx):
        for i in range(ctx.params['amount']):
            idx = str(i).zfill(3)
            machine_name = "client{}".format(idx)
            yield (
                {
                    "hostname": "%s.%s" % (machine_name, self.domain.lower()),
                    "type": "client"
                }
            )

    def run(self, ctx):
        # Configure clients before installation
        args = {
            "server_ip": self.provider.hosts["server"],
            "domain": self.domain
        }
        self.run_ansible_playbook_from_template(ANSIBLE_ENROLLMENTTEST_CLIENT_CONFIG_PLAYBOOK,
                                                "enrollmenttest_client_config", args, ctx)

        # Client installations will be triggered at now + 1min per 20 clients
        wait_time = max(int(len(self.provider.hosts.keys()) / 20), 1) * 60
        client_install_time = int(time.time()) + wait_time

        client_cmds = [
            ("sleep $(( {} - $(date +%s) )) "
             "> ~/install-cmd-output 2>&1").format(str(client_install_time)),
            "sudo ipa-client-install -p admin -w password -U "
            "--enable-dns-updates --no-nisdomain -N >> ~/install-cmd-output 2>&1",
        ]
        processes = {}
        non_client_hosts = 0
        for host, ip in self.provider.hosts.items():
            if host == "server" or host.startswith("replica"):
                non_client_hosts += 1
                continue
            processes[host] = self.run_ssh_command(" && ".join(client_cmds), ip, ctx, False)
        print(
            "Client installation commands sent, client install will start at %s"
            % time.ctime(client_install_time)
        )
        print("Waiting for client installs to be completed...")

        start_time = time.time()
        self.clients_succeeded = 0
        clients_returncodes = ""
        for host, proc in processes.items():
            proc.communicate()
            returncode = proc.returncode
            rc_str = "Host " + host + " returned " + str(returncode)
            clients_returncodes += rc_str + "\n"
            if returncode == 0:
                self.clients_succeeded += 1
        self.execution_time = time.time() - start_time - wait_time
        print("Clients succeeded: %s" % str(self.clients_succeeded))
        print("Return codes written to sync directory.")
        with open("sync/returncodes", "w") as f:
            f.write(clients_returncodes)

        # Check all hosts have been registered in server
        ansible_ret = self.run_ansible_playbook_from_template(
            ANSIBLE_COUNT_IPA_HOSTS_PLAYBOOK,
            "enrollmenttest_count_hosts", {}, ctx
        )
        server_ip = self.provider.hosts["server"]
        host_find_output = ansible_ret.get_fact_cache(server_ip)["host_find_output"]
        try:
            if (
                int(host_find_output) == self.clients_succeeded + non_client_hosts
                and len(self.provider.hosts.keys()) == self.clients_succeeded + non_client_hosts
            ):
                yield Result(self, SUCCESS, msg="All clients enrolled succesfully.",
                             successes=self.clients_succeeded)
            else:
                yield Result(self, ERROR,
                             error="Client installs succeeded number (%s) "
                             "does not match host-find output (%s)."
                             % (self.clients_succeeded, host_find_output),
                             successes=self.clients_succeeded)
        except ValueError:
            yield Result(self, ERROR,
                         error="Failed to convert host-find output to int. Value was: %s"
                         % host_find_output)

        self.results_archive_name = "EnrollmentTest-{}-{}-{}servers-{}clients-{}fails".format(
            datetime.now().strftime("%FT%H%MZ"),
            self.provider.server_image.replace("/", ""),
            non_client_hosts,
            len(processes),
            len(processes) - self.clients_succeeded
        )

        return

    def post_process_logs(self, ctx):
        """ Calculate enrollment distribution between servers """
        if ctx.params['replicas'] <= 0:
            return

        server_count = dict()
        n_clients = 0
        for f in os.listdir("sync"):
            if f.startswith("client"):
                n_clients += 1
                logpath = "sync/{}/ipaclient-install.log".format(f)
                try:
                    logstr = open(logpath).readlines()
                except FileNotFoundError:
                    yield Result(self, WARNING, msg="File %s not found" % logpath)
                    continue
                for line in logstr:
                    if "discovered server" in line:
                        hostname = line.strip().split(" ")[-1]
                        if hostname in server_count:
                            server_count[hostname] += 1
                        else:
                            server_count[hostname] = 1
                        break

        for server, enrollments in server_count.items():
            percentage = round((enrollments / n_clients) * 100)
            yield Result(self, SUCCESS,
                         msg="Server %s managed %s out of %s enrollments (%s)"
                         % (server, enrollments, n_clients, percentage))
