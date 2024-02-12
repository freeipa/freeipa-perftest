#
# Copyright (C) 2024 FreeIPA Contributors see COPYING for license
#

import os
import random
import resource
import subprocess as sp
import time
from datetime import datetime

from ipaperftest.core.plugin import Plugin, Result
from ipaperftest.core.constants import (
    SUCCESS,
    WARNING,
    ERROR,
    ANSIBLE_ENROLLMENTTEST_CLIENT_CONFIG_PLAYBOOK,
    ANSIBLE_COUNT_IPA_HOSTS_PLAYBOOK,
    ANSIBLE_CERTISSUANCETEST_SERVER_TUNING_PLAYBOOK,
    ANSIBLE_CERTISSUANCETEST_SERVER_CONFIG_PLAYBOOK)
from ipaperftest.plugins.registry import registry


@registry
class CertIssuanceTest(Plugin):

    def __init__(self, registry):
        super().__init__(registry)
        self.custom_logs = ["getcert.log", ]

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

    def validate_options(self, ctx):
        if not ctx.params.get('threads'):
            raise RuntimeError('threads number is required')

    def install_server(self, ctx):
        if ctx.params["ad_threads"] > 0:
            # install AD server
            self.run_ansible_playbook_from_template(
                ANSIBLE_CERTISSUANCETEST_SERVER_CONFIG_PLAYBOOK,
                "authenticationtest_ad_server_setup", {}, ctx
            )
        super().install_server(ctx)

    def run(self, ctx):
        sp.run(["cp", "create-test-data.py", "runner_metadata/"])

        # Configure clients before installation
        args = {
            "server_ip": self.provider.hosts["server"],
            "domain": self.domain
        }
        self.run_ansible_playbook_from_template(
            ANSIBLE_ENROLLMENTTEST_CLIENT_CONFIG_PLAYBOOK,
            "certissuetest_client_config", args, ctx
        )

        # Clients installation
        client_cmds = [
            "sudo ipa-client-install -p admin -w password -U "
            "--enable-dns-updates --no-nisdomain -N",
        ]
        processes = {}
        non_client_hosts = 0
        installed = 0
        sleep_time = 20
        for host, ip in self.provider.hosts.items():
            if not host.startswith("client"):
                if host.startswith("server") or host.startswith("replica"):
                    non_client_hosts += 1
                continue
            installed += 1
            # spread the client install time to hopefully have all pass
            if installed % 30 == 0:
                sleep_time += 20
            cmds = ["sleep {}".format(sleep_time + random.randrange(1, 10))] + client_cmds
            proc = self.run_ssh_command(" && ".join(cmds), ip, ctx, False)
            processes[host] = proc

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
        ansible_ret = self.run_ansible_playbook_from_template(
            ANSIBLE_COUNT_IPA_HOSTS_PLAYBOOK,
            "enrollmenttest_count_hosts", {}, ctx
        )
        server_ip = self.provider.hosts["server"]
        host_find_output = ansible_ret.get_fact_cache(server_ip)["host_find_output"]
        try:
            if (
                int(host_find_output) == (self.clients_succeeded + non_client_hosts)
                and len(self.provider.hosts.keys()) == (self.clients_succeeded +
                                                        non_client_hosts)
            ):
                yield Result(self, SUCCESS, msg="All clients enrolled succesfully.")
            else:
                yield Result(self, ERROR,
                             error="Client installs succeeded number (%s) "
                             "does not match host-find output (%s)." %
                             (self.clients_succeeded, host_find_output))
        except ValueError:
            yield Result(self, ERROR,
                         error="Failed to convert host-find output to int. "
                               "Value was: %s" % host_find_output)

        args = {
            "amount": ctx.params["amount"],
            "services": ctx.params["cert_requests"],
            "wsgi_processes": ctx.params["wsgi_processes"],
        }
        self.run_ansible_playbook_from_template(
            ANSIBLE_CERTISSUANCETEST_SERVER_CONFIG_PLAYBOOK,
            "certissuancetest_server_config", args, ctx
        )
        self.run_ansible_playbook_from_template(
            ANSIBLE_CERTISSUANCETEST_SERVER_TUNING_PLAYBOOK,
            "certissuancetest_server_tuning", args, ctx
        )

        # Client authentications will be triggered at now + 1min per 20 clients
        # wait_time = max(int(len(self.provider.hosts.keys()) / 20), 1) * 60
        client_wait_time = int(time.time()) + 30

        # Now that all the client installs are done, fire off the
        # certificate requests (for now whether all installs are ok or not)
        resource.setrlimit(resource.RLIMIT_NOFILE, (16384, 16384))
        processes = []
        for host, ip in self.provider.hosts.items():
            if not host.startswith("client"):
                continue
            for i in range(ctx.params["cert_requests"]):
                service_cmd = 'sudo ipa-getcert request -K service{}/{}.{} '\
                    '-f /etc/pki/tls/certs/service{}.pem ' \
                    '-k /etc/pki/tls/private/service{}.key -v -w >> request.log 2>&1' \
                    .format(i, host, self.domain.lower(), i, i)
                try:
                    proc = self.run_ssh_command(service_cmd, ip, ctx, False)
                    processes.append(proc)
                except IOError:
                    print("Length of procs ", len(processes))
                    raise

        print("Waiting for certificate issuance to be completed...")

        start_time = time.time()
        for proc in processes:
            proc.communicate()
        self.execution_time = time.time() - start_time - client_wait_time

        # Get the getcert output
        processes = {}
        cmds = []
        for host, ip in self.provider.hosts.items():
            if not host.startswith("client"):
                continue
            for i in range(ctx.params["cert_requests"]):
                cmds.append('sudo ipa-getcert list > getcert.log')
            proc = self.run_ssh_command(" && ".join(cmds), ip, ctx, False)
            processes[host] = proc

        print("Waiting for collection of getcert output to be completed...")

        start_time = time.time()
        for host, proc in processes.items():
            proc.communicate()
        self.execution_time = time.time() - start_time - client_wait_time

        return

    def post_process_logs(self, ctx):
        """ Calculate number of succeeded threads """

        total_successes = 0
        total_requested = 0
        for host in os.listdir("sync"):
            if not host.startswith("client"):
                continue

            logpath = "sync/{}/getcert.log".format(host)
            try:
                logstr = open(logpath).readlines()
            except FileNotFoundError:
                yield Result(self, WARNING, msg="File %s not found" % logpath)
                continue

            n_requested = 0
            n_succeeded = 0
            for line in logstr:
                if "status:" not in line:
                    continue

                n_requested += 1
                if 'MONITORING' in line:
                    n_succeeded += 1

            if n_requested > 0:
                percentage = round((n_succeeded / n_requested) * 100)
            else:
                percentage = 0
            if percentage == 100:
                yield Result(self, SUCCESS, msg="All threads on %s succeeded." % host)
            else:
                yield Result(self, ERROR,
                             error="Not all threads on %s succeded: %s/%s (%s)."
                             % (host, n_succeeded, n_requested, percentage))

            total_successes += n_succeeded
            total_requested += n_requested

        if total_requested == 0:
            yield Result(self, ERROR,
                         error="None of the requests succeeded.")
        total_percentage = round((total_successes / total_requested) * 100)

        yield Result(self, SUCCESS, msg="{} requests out of {} succeeded ({}%)".format(
            total_successes, total_requested, total_percentage), successes=total_successes)

        if total_percentage == 100:
            msg = "success"
            yield Result(self, SUCCESS, msg="All requests succeded.")
        else:
            msg = "fails"
            yield Result(self, ERROR,
                         error="Not all requests succeeded: %s/%s (%s)."
                         % (total_successes, total_requested, total_percentage))

        if total_requested != total_successes:
            msg = "fails"

        self.results_archive_name = \
            "CertIssuanceTest-{}-{}-{}clients-{}requests-{}issued-{}".format(
                datetime.now().strftime("%FT%H%MZ"),
                self.provider.server_image.replace("/", ""),
                ctx.params["amount"],
                total_requested,
                total_successes,
                msg,)
