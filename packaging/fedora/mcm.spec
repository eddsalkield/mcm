Summary: Meta-configuration manager, for scm
Name: mcm
Version: 0.0.2
Release: 2%{?dist}
Source0: mcm-%{version}.tar.gz
License: UNKNOWN

BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-buildroot
Prefix: %{_prefix}
BuildArch: noarch
Vendor: Edd Salkield <edd@salkield.uk>

Requires: python3 python3-pyxdg python3-toml python3-jsonschema
Requires: scm

%description
A meta-configuration manager for scm

%prep
%setup -n %{name}-%{version} -n %{name}-%{version}

%build
python3 setup.py build

%install
python3 setup.py install --single-version-externally-managed -O1 --root=$RPM_BUILD_ROOT --record=INSTALLED_FILES

%clean
rm -rf $RPM_BUILD_ROOT

%files -f INSTALLED_FILES
%defattr(-,root,root)
