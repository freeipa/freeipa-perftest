# Required initializer
AC_INIT([freeipa-perftest],[0.4.1])

# Automake initialization
AM_INIT_AUTOMAKE([foreign])

# Add a test for a compiler.
AC_PROG_CC
AM_PROG_CC_C_O
AC_CONFIG_HEADERS([config.h])

# Check for header files
AC_HEADER_STDC
AC_CHECK_HEADERS( \
unistd.h
)

# Check for typedefs, structures, and compiler characteristics.
AC_C_CONST

# Write config.status and the Makefile
AC_OUTPUT(Makefile)
