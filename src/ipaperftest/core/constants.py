#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

# flake8: noqa
# Error reporting result
SUCCESS = 0
WARNING = 10
ERROR = 20
CRITICAL = 30

_levelToName = {
    SUCCESS: 'SUCCESS',
    WARNING: 'WARNING',
    ERROR: 'ERROR',
    CRITICAL: 'CRITICAL',
}

_nameToLevel = {
    'SUCCESS': SUCCESS,
    'WARNING': WARNING,
    'ERROR': ERROR,
    'CRITICAL': CRITICAL,
}


def getLevelName(level):
    """
    Translate between level constants and their textual mappings.

    If the level is one of the predefined levels then returns the
    corresponding string.

    If a numeric value corresponding to one of the defined levels
    is passed in instead the corresponding string representation is
    returned.
    """
    name = _levelToName.get(level) or _nameToLevel.get(level)
    if name is not None:
        return name

    return level


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
ipaadmin_password=password
ipasssd_enable_dns_updates=yes
ipaclient_no_nisdomain=yes
ipaclient_no_ntp=yes
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
  become: yes
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
  become: yes
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

ANSIBLE_SERVER_CONFIG_PLAYBOOK = """
---
- name: Configure server before installation
  hosts: ipaserver
  become: yes
  tasks:
    - sysctl:
        name: net.ipv6.conf.all.disable_ipv6
        value: '0'
        sysctl_set: yes
    - replace:
        path: /etc/hosts
        regexp: '127.*.*.*\\s*server'
        replace: '{server_ip} server.{domain} server/'
"""

ANSIBLE_REPLICA_CONFIG_PLAYBOOK = """
---
- name: Configure {replica_name} before installation
  hosts: {replica_name}
  become: yes
  tasks:
    - lineinfile:
        path: /etc/hosts
        line: '{server_ip} server.{domain} server'
    - lineinfile:
        path: /etc/resolv.conf
        line: nameserver {server_ip}
    - lineinfile:
        path: /etc/hosts
        regexp: '127.*.*.*\\s*replica*'
        state: absent
    - lineinfile:
        path: /etc/hosts
        line: {replica_ip} {replica_name}.{domain} {replica_name}
"""

ANSIBLE_ENABLE_DATA_COLLECTION_PLAYBOOK = """
---
- name: Enable data collection using SAR
  hosts: ipaserver
  tasks:
    - shell:
        cmd: "nohup sar -o ~/saroutput 2 >/dev/null 2>&1 &"
"""

ANSIBLE_ENROLLMENTTEST_CLIENT_CONFIG_PLAYBOOK = """
---
- name: Configure client machines before installation
  hosts: ipaclients
  become: yes
  tasks:
    - lineinfile:
        path: /etc/resolv.conf
        regexp: ".*"
        state: absent
    - lineinfile:
        path: /etc/resolv.conf
        line: nameserver {server_ip}
    - lineinfile:
        path: /etc/hosts
        line: {server_ip} server.{domain} server
"""

ANSIBLE_COUNT_IPA_HOSTS_PLAYBOOK = """
---
- name: Count hosts registered in IPA server
  hosts: ipaserver
  tasks:
    - command: "kinit admin"
      args:
        stdin: "password"
    - shell:
        cmd: "ipa host-find --sizelimit=0 | grep 'Host name:' | wc -l"
      register: host_find_output
    - set_fact:
        host_find_output: "{{{{ host_find_output.stdout }}}}"
        cacheable: yes
"""

ANSIBLE_APITEST_CLIENT_CONFIG_PLAYBOOK = """
---
- name: Configure client machines before installation
  hosts: ipaclients
  become: yes
  tasks:
    - lineinfile:
        path: /etc/resolv.conf
        regexp: ".*"
        state: absent
    - lineinfile:
        path: /etc/resolv.conf
        line: nameserver {server_ip}
    - lineinfile:
        path: /etc/hosts
        line: {server_ip} server.{domain} server
"""

ANSIBLE_AUTHENTICATIONTEST_SERVER_CONFIG_PLAYBOOK = """
---
- name: Configure server before execution
  hosts: ipaserver
  become: yes
  tasks:
    - synchronize:
        src: "{{{{ item }}}}"
        dest: "/root"
        mode: push
        use_ssh_args: yes
      with_items:
        - create-test-data.py
        - set-password.py
    - package:
        name: python3-click
        state: present
    - command:
        cmd: "python create-test-data.py --hosts {amount} --outfile userdata.ldif --users-per-host {threads}"
        chdir: /root
    - command: "kinit admin"
      args:
        stdin: "password"
    - ipaconfig:
        enable_migration: yes
    - command:
        cmd: "ldapadd -x -D 'cn=Directory Manager' -w password -f userdata.ldif"
        chdir: /root
    - command:
        cmd: "python set-password.py --dm-password password --hosts {amount} --users-per-host {threads}"
        chdir: /root
    - ipaconfig:
        enable_migration: no
"""

ANSIBLE_AUTHENTICATIONTEST_CLIENT_CONFIG_PLAYBOOK = """
---
- name: Configure clients before installation
  hosts: ipaclients
  become: yes
  tasks:
    - yum_repository:
        name: freeipa_freeipa-perftest-copr-repo
        baseurl: https://download.copr.fedorainfracloud.org/results/@freeipa/freeipa-perftest/fedora-$releasever-$basearch/
        gpgkey: https://download.copr.fedorainfracloud.org/results/@freeipa/freeipa-perftest/pubkey.gpg
        description: "Copr repo for freeipa-perftest owned by @freeipa"
    - package:
        name: freeipa-perftest-client
        state: present
    - lineinfile:
        path: /etc/resolv.conf
        regexp: ".*"
        state: absent
    - lineinfile:
        path: /etc/resolv.conf
        line: nameserver {server_ip}
    - lineinfile:
        path: /etc/hosts
        line: {server_ip} server.{domain} server
    - lineinfile:
        path: /etc/pam.d/login
        regexp: "\\\\.*pam_loginuid.so"
        state: absent
"""
