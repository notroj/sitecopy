from common import *

def test_vsftpd(sitecopy_ftp_env, vsftpd_container):
    check_update_cycle(sitecopy_ftp_env)
