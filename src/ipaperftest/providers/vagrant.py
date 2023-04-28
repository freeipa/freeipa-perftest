#
# Copyright (C) 2022 FreeIPA Contributors see COPYING for license
#

import os
import subprocess as sp
from ipaperftest.core.constants import VAGRANT_HOST_TEMPLATE, VAGRANTFILE_TEMPLATE
from ipaperftest.providers.provider import Provider


class VagrantProvider(Provider):
    """
    Vagrant provider.
    """

    def __init__(self):
        super().__init__()
        self.files_to_log.append("Vagrantfile")
        self.default_private_key = "~/.vagrant.d/insecure_private_key"
        self.windows_admin_password = "vagrant"

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
                    raise RuntimeError("Ran out of IP addresses for private network")

    def cleanup(self, ctx):
        """We clean up *before* an execution so that the VMs remain.

           This is so we can evaluate what, if anything, went wrong.
        """

        if os.path.exists("Vagrantfile"):
            sp.run(["vagrant", "destroy", "-f"], stdout=sp.PIPE)
            sp.run(["systemctl", "restart", "libvirtd"], stdout=sp.PIPE)
            sp.run(["sleep", "5"], stdout=sp.PIPE)

    def generate_metadata(self, ctx, machine_configs, domain):
        """Create the Vagrantfile
           This directly controls creating the entries for the server
           and replicas. A per-test generator is used to generate the
           client entries.
        """

        types = {
            "server": {
                "memory": 8192,
                "cpus": 4,
            },
            "client": {
                "memory": 2048,
                "cpus": 1,
            },
            "ad": {
                "memory": 8192,
                "cpus": 4
            }
        }

        server_img = ctx.params["server_image"]
        client_img = ctx.params["client_image"]
        self.server_image = server_img if server_img else "fedora/38-cloud-base"
        self.client_image = client_img if client_img else "fedora/38-cloud-base"

        images = {
            "server": self.server_image,
            "client": self.client_image,
            "ad": "peru/windows-server-2019-standard-x64-eval",
        }

        ad_extra_options = """
            {hostname}.vm.network :forwarded_port, guest: 3389, host:3389, id: "rdp", auto_correct:true
            {hostname}.vm.network :forwarded_port, guest: 5986, host:5986, id: "winrm-ssl", auto_correct:true
            {hostname}.vm.communicator = "winrm"
            {hostname}.winrm.communicator = "winrm"
            {hostname}.winrm.username = "Administrator"
            {hostname}.winrm.retry_limit = 50
            {hostname}.winrm.retry_delay = 10
        """  # noqa: E501

        ip_generator = self.generate_ip()

        hosts_metadata = ""
        for conf in machine_configs:
            hosts_metadata += VAGRANT_HOST_TEMPLATE.format(
                machine_name=conf['hostname'].split(".")[0],
                hostname=conf['hostname'],
                memory=types[conf["type"]]["memory"],
                cpus=types[conf["type"]]["cpus"],
                box=images[conf['type']],
                ip=next(ip_generator),
                extra_options=ad_extra_options.format(
                    hostname=conf['hostname']) if conf['type'] == "ad" else ""
            )

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
            machine_configs=hosts_metadata,
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
