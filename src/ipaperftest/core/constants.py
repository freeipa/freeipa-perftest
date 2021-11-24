#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#


VAGRANTFILE_TEMPLATE = """
    Vagrant.configure("2") do |config|
        config.vm.synced_folder ".", "/vagrant", disabled: true
        config.vm.provider :libvirt do |libvirt|
            # Disabling QEMU Session as it causes issues with private network
            # https://fedoraproject.org/wiki/Changes/Vagrant_2.2_with_QEMU_Session
            libvirt.qemu_use_session = false
            libvirt.management_network_address = "192.168.3.0/16"
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
ipaserver_auto_forwarders=yes
ipaserver_auto_reverse=yes

[ipareplicas]
{replica_hostnames}

[ipareplicas:vars]
ipaadmin_password=password
ipadm_password=password
ipareplica_domain={domain}
ipaserver_realm={realm}
ipareplica_setup_dns=yes
ipareplica_auto_forwarders=yes
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
  hosts: ipaserver, ipareplicas
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
{custom_logs}

"""
