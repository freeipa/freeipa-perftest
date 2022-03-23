#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import math
import os
import subprocess as sp
import time
import ansible_runner
from datetime import datetime

from ipaperftest.core.plugin import Plugin, Result
from ipaperftest.core.constants import (
    SUCCESS,
    ERROR,
    MACHINE_CONFIG_TEMPLATE,
    ANSIBLE_APITEST_CLIENT_CONFIG_PLAYBOOK)
from ipaperftest.plugins.registry import registry


@registry
class APITest(Plugin):

    def __init__(self, registry):
        super().__init__(registry)
        self.custom_logs = ["command*log", ]

    def generate_clients(self, ctx):
        self.commands_per_client = 25
        n_clients = math.ceil(ctx.params['amount'] / self.commands_per_client)
        for i in range(n_clients):
            idx = str(i).zfill(3)
            machine_name = "client{}".format(idx)
            yield(
                MACHINE_CONFIG_TEMPLATE.format(
                    machine_name=machine_name,
                    box=ctx.params['client_image'],
                    hostname=machine_name + "." + self.domain.lower(),
                    memory_size=2048,
                    cpus_number=1,
                    extra_options="",
                    extra_commands="",
                    ip=next(self.ip_generator),
                )
            )

    def validate_options(self, ctx):
        if not ctx.params.get('command'):
            raise RuntimeError('command is required')

    def run(self, ctx):
        print("Deploying clients...")

        args = {
            "server_ip": self.hosts["server"],
            "domain": self.domain
        }
        self.run_ansible_playbook_from_template(ANSIBLE_APITEST_CLIENT_CONFIG_PLAYBOOK,
                                                "apitest_client_config", args, ctx)
        ansible_runner.run(private_data_dir="runner_metadata",
                           playbook="ansible-freeipa/playbooks/install-client.yml",
                           verbosity=1,
                           cmdline="--ssh-extra-args '-F vagrant-ssh-config' "
                                   "--flush-cache")

        # Wait 2 min per client before running the commands
        clients = [name for name, ip in self.hosts.items() if name.startswith("client")]
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

        for client in clients:
            sp.run("vagrant ssh {} -c 'echo password | kinit admin'".format(client),
                   shell=True,
                   stdin=sp.DEVNULL,
                   stdout=sp.PIPE,
                   stderr=sp.PIPE)

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
            sp.run(
                'vagrant ssh {} -c "{}"'.format(clients[id], " && ".join(command_list)),
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

        self.results_archive_name = "APITest-{}-{}-{}commands-{}fails".format(
            datetime.now().strftime("%FT%H%MZ"),
            ctx.params['server_image'].replace("/", ""),
            ctx.params['amount'],
            ctx.params['amount'] - commands_succeeded
        )
