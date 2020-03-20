if [ -z "$1" ]; then
	echo "Must provide version as argument"
else
	fedpkg --release f31 local
	rpmbuild --buildroot . --rebuild mcm-$1.src.rpm
fi
