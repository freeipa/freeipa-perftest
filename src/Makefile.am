bin_PROGRAMS = pamtest

pamtest_SOURCES = pamtest.c

LIBS=-lpam -lpam_misc -lkrb5 -lk5crypto -lcom_err -lpopt -lpthread

MAINTAINERCLEANFILES =	\
	*~					\
	Makefile.in			\
	aclocal.m4			\
	compile				\
	config.guess		\
	config.log			\
	config.sub			\
	config.h.in			\
	configure			\
	depcomp				\
	install-sh			\
	ltmain.sh			\
	missing

.PHONY: all test clean
