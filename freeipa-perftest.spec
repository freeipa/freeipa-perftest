Name:           freeipa-perftest
Version:        0.4
Release:        1%{?dist}
Summary:        A set of IPA performance tools

License:        GPLv3
URL:            https://github.com/freeipa/freeipa-perftest.git
Source0:        https://github.com/freeipa/freeipa-perftest/archive/%{version}.tar.gz

BuildRequires:  pam-devel
BuildRequires:  krb5-devel
BuildRequires:  popt-devel
BuildRequires:  glibc-devel
BuildRequires:  autoconf
BuildRequires:  automake
BuildRequires:  gcc
BuildRequires:	python3-devel
BuildRequires:  python3-setuptools

%description
freeipa-perftest is a performance measurement tool for
specific use-cases.

%package client
Summary:        client-side IPA performance tools
Requires:       pam
Requires:       krb5-workstation
Requires:       popt

%description client
freeipa-perftest is a performance measurement tool for
specific use-cases.

%package controller
Summary:        controller-side IPA performance tools
BuildArch:      noarch
Requires:       vagrant
Requires:       vagrant-libvirt
Requires:       libvirt
Requires:       ansible
Requires:       git
Requires:       rsync

%description controller
freeipa-perftest is a performance measurement tool for
specific use-cases.

%prep
%autosetup -p1 -n freeipa-perftest-%{version}


%build
pushd src
autoreconf -i -f

%configure
%make_build
popd
%py3_build


%install
rm -rf $RPM_BUILD_ROOT
pushd src
%make_install
popd
%py3_install


%files client
%license COPYING
%doc README.md
%{_bindir}/pamtest

%files controller
%license COPYING
%doc README.md
%{_bindir}/ipaperftest
%{python3_sitelib}/ipaperftest
%{python3_sitelib}/ipaperftest-%{version}-*.egg-info/
%{python3_sitelib}/ipaperftest-%{version}-*-nspkg.pth


%changelog
* Wed Aug 24 2022 Antonio Torres <antorres@redhat.com> - 0.4-1
- Update to 0.4 upstream release

* Tue Apr 26 2022 Antonio Torres <antorres@redhat.com> - 0.3-1
- Update to 0.3 upstream release

* Thu Dec 16 2021 Antonio Torres <antorres@redhat.com> - 0.2-1
- Use Ansible playbooks for hosts configuration

* Tue Nov 16 2021 Rob Crittenden <rcritten@redhat.com> - 0.1-1
- Initial release
