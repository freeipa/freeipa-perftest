#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import math
import subprocess as sp
import time

from ipaperftest.core.main import Plugin
from ipaperftest.core.constants import MACHINE_CONFIG_TEMPLATE
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
                    memory_size=384,
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

        for i in range(ctx.params['amount']):
            client_idx = math.floor(i / 50)
            formated_api_cmd = ctx.params['command'].format(id=str(i))
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
            with open("sync/command{}log".format(str(i)), "w") as f:
                f.writelines("\n".join(file_lines))
        print("Return codes written to sync directory.")
        with open("sync/returncodes", "w") as f:
            f.write(returncodes)

        if commands_succeeded == ctx.params['amount']:
            print("All commands executed succesfully.")
        else:
            print("ERROR: not all commands completed succesfully. Check logs.")
