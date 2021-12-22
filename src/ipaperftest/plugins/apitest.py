#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import math
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

    def generate_clients(self, ctx):
        for i in range(ctx.params['amount']):
            idx = str(i).zfill(3)
            machine_name = "client{}".format(idx)
            yield(
                MACHINE_CONFIG_TEMPLATE.format(
                    machine_name=machine_name,
                    box=ctx.params['client_image'],
                    hostname=machine_name + "." + self.domain.lower(),
                    memory_size=768,
                    cpus_number=1,
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

        for i in range(ctx.params['amount']):
            client_idx = math.floor(i / 50)
            self.custom_logs.append("command{}log".format(str(i)))
            formated_api_cmd = ctx.params['command'].format(id=str(i))
            cmd = (
                r"echo password | kinit admin;"
                r"echo 'echo {cmd} > ~/command{id}log;"
                r"{cmd} >> ~/command{id}log 2>&1;"
                r"echo \$? >> ~/command{id}log' "
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
        for i in range(ctx.params['amount']):
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
