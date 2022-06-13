#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import math
import os
import time
import ansible_runner
from datetime import datetime

from ipaperftest.core.plugin import Plugin, Result
from ipaperftest.core.constants import (
    ANSIBLE_APITEST_CLIENT_UPLOAD_SEQUENTIAL_SCRIPT_PLAYBOOK,
    SUCCESS,
    ERROR,
    ANSIBLE_APITEST_CLIENT_CONFIG_PLAYBOOK)
from ipaperftest.plugins.registry import registry


@registry
class APITest(Plugin):

    def __init__(self, registry):
        super().__init__(registry)
        self.custom_logs = ["command*log", ]

    def generate_clients(self, ctx):
        if ctx.params['sequential']:
            # We only need a single client for sequential mode
            n_clients = 1
        else:
            self.commands_per_client = 25
            n_clients = math.ceil(ctx.params['amount'] / self.commands_per_client)
        for i in range(n_clients):
            idx = str(i).zfill(3)
            machine_name = "client{}".format(idx)
            yield(
                {
                    "hostname": "%s.%s" % (machine_name, self.domain.lower()),
                    "type": "client"
                }
            )

    def validate_options(self, ctx):
        if not ctx.params.get('command'):
            raise RuntimeError('command is required')

    def run_simultaneously(self, ctx):
        # Wait 2 min per client before running the commands
        clients = [name for name, _ in self.provider.hosts.items() if name.startswith("client")]
        local_run_time, epoch_run_time = (
            self.run_ssh_command(
                "date --date now+{}min '+%H:%M %s'"
                .format(str(len(clients) * 2)),
                self.provider.hosts[clients[0]], ctx)
            .stdout.decode("utf-8")
            .strip().split(" ")
        )

        # commands[0] -> list of commands for client #1
        commands = [[] for _ in clients]
        for i in range(ctx.params['amount']):
            client_idx = math.floor(i / self.commands_per_client)
            id_str = str(i).zfill(len(str(ctx.params['amount'])))
            formated_api_cmd = ctx.params['command'].format(id=id_str)
            cmd = (
                r"echo 'echo {cmd} > ~/command{id}log;"
                r"{cmd} >> ~/command{id}log 2>&1;"
                r"echo \$? >> ~/command{id}log' "
                r"| at {time}".format(
                 cmd=formated_api_cmd, id=str(i), time=local_run_time)
            )
            commands[client_idx].append(cmd)
        for id, command_list in enumerate(commands):
            self.run_ssh_command(" && ".join(command_list), self.provider.hosts[clients[id]], ctx)

        print("Commands will be run at %s (machine local time)" % local_run_time)
        sleep_time = int(epoch_run_time) - time.time()
        time.sleep(sleep_time)
        # Wait until all atd commands have completed
        # (that is, once /var/spool/at only has the 'spool' dir)

        start_time = time.time()
        while True:
            clients_cmds_pending = []
            for client in clients:
                cmds_pending = (
                    self.run_ssh_command("sudo ls /var/spool/at | wc -l",
                                         self.provider.hosts[client], ctx)
                    .stdout.decode("utf-8")
                    .strip()
                )
                clients_cmds_pending.append(cmds_pending)
            if all([cmds == "1" for cmds in clients_cmds_pending]):
                break
            time.sleep(5)
        end_time = time.time()
        self.execution_time = end_time - start_time

    def run_sequentially(self, ctx):
        commands = []
        for i in range(ctx.params['amount']):
            id_str = str(i).zfill(len(str(ctx.params['amount'])))
            formated_api_cmd = ctx.params["command"].format(id=id_str)
            cmd = (
                r"echo {cmd} > ~/command{id}log;"
                r"{cmd} >> ~/command{id}log 2>&1;"
                r"echo $? >> ~/command{id}log".format(
                    cmd=formated_api_cmd, id=str(i)
                )
            )
            commands.append(cmd)

        with open("runner_metadata/apitest_sequential_commands.sh", "w") as f:
            f.write("#!/bin/sh\n")
            for cmd in commands:
                f.write(cmd + "\n")

        self.run_ansible_playbook_from_template(
            ANSIBLE_APITEST_CLIENT_UPLOAD_SEQUENTIAL_SCRIPT_PLAYBOOK,
            "apitest_sequential_script_upload", {}, ctx)

        start_time = time.time()
        self.run_ssh_command("/bin/sh apitest_sequential_commands.sh",
                             self.provider.hosts["client000"], ctx)
        end_time = time.time()
        self.execution_time = end_time - start_time

    def run(self, ctx):
        print("Deploying clients...")

        args = {
            "server_ip": self.provider.hosts["server"],
            "domain": self.domain
        }
        self.run_ansible_playbook_from_template(ANSIBLE_APITEST_CLIENT_CONFIG_PLAYBOOK,
                                                "apitest_client_config", args, ctx)
        ansible_runner.run(private_data_dir="runner_metadata",
                           playbook="ansible-freeipa/playbooks/install-client.yml",
                           verbosity=1)

        clients = [name for name, _ in self.provider.hosts.items() if name.startswith("client")]
        for client in clients:
            self.run_ssh_command("echo password | kinit admin", self.provider.hosts[client], ctx)

        if ctx.params["sequential"]:
            self.run_sequentially(ctx)
        else:
            self.run_simultaneously(ctx)

    def post_process_logs(self, ctx):
        commands_succeeded = 0
        returncodes = ""

        for f in os.listdir("sync"):
            if f.startswith("client"):
                for logfile in os.listdir("sync/%s" % f):
                    if logfile.startswith("command"):
                        cmd_lines = open("sync/{}/{}".format(f, logfile)).readlines()
                        rc = cmd_lines[-1].strip()
                        rc_str = "Command '{}' returned {} on {}".format(
                            cmd_lines[0].strip(), rc, f
                        )
                        print(rc_str)
                        returncodes += rc_str + "\n"
                        if rc == "0":
                            commands_succeeded += 1
        print("Return codes written to sync directory.")
        with open("sync/returncodes", "w") as f:
            f.write(returncodes)

        if commands_succeeded == ctx.params['amount']:
            yield Result(self, SUCCESS, msg="All commands executed successfully.")
        else:
            yield Result(self, ERROR,
                         error="Not all commands completed succesfully (%s/%s). "
                         "Check logs." % (commands_succeeded, ctx.params['amount']))

        yield Result(self, SUCCESS, msg="Test executed in {} seconds.".format(self.execution_time))

        self.results_archive_name = "APITest-{}-{}-{}-{}commands-{}fails-{}s".format(
            "sequential" if ctx.params["sequential"] else "simultaneous",
            datetime.now().strftime("%FT%H%MZ"),
            self.provider.server_image.replace("/", ""),
            ctx.params['amount'],
            ctx.params['amount'] - commands_succeeded,
            int(self.execution_time)
        )
