#!/usr/bin/env python
# format: utf-8
from __future__ import print_function
import argparse
import sys
from os.path import (
    isfile,
    isdir,
    realpath,
    join,
    dirname
)
import os
import subprocess
from subprocess import Popen, TimeoutExpired
import shlex
from collections import namedtuple
from time import sleep
from sqlalchemy import create_engine
import phpserialize
import datetime

sh_quote = shlex.quote


PROGRAM_NAME = 'container_from_sqldump'
VERSION = '1.0'
ROOT_PATH = dirname(__file__)


ProcResult = namedtuple('ProcResult', ('returncode', 'stdout', 'stderr'))


class ValidationError(ValueError):
    pass


def is_successful(cmd):
    try:
        completed = run(cmd)
        if completed.returncode != 0:
            return False
    except subprocess.CalledProcessError:
        return False
    return True


def run(cmd, **args):
    print("- running \"{0}\" with args {1}".format(cmd, args))
    if 'debug' in args:
        debug = args['debug']
        del args['debug']
    else:
        debug = False
    defaults = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    defaults.update(args)
    cmd_sequence = shlex.split(cmd)
    proc_result = ProcResult(stdout='',
                             stderr='',
                             returncode=None)
    with Popen(cmd_sequence, **defaults) as proc:
        stdout, stderr = ('', '')
        while proc.poll() is None:
            try:
                stdout, stderr = proc.communicate()
                if debug:
                    if stdout:
                        for l in stdout.decode('utf-8').split('\n'):
                            print(l)
                    if stderr:
                        for l in stderr.decode('utf-8').split('\n'):
                            print(l)
            except TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
        proc_result = ProcResult(stdout=stdout,
                                 stderr=stderr,
                                 returncode=proc.returncode)
    return proc_result


def build_arg_parser():
    parser = argparse.ArgumentParser(description='Spin an isolated WP container')
    parser.add_argument('container_name', type=str,
                        help='container_name')
    parser.add_argument('dump_file', type=str, default='',
                        help='dump_file')
    parser.add_argument('--mysql-password', dest='mysql_password', type=str,
                        default='wordpress', help='Mysql Password')
    parser.add_argument('--mysql-user', dest='mysql_user', type=str,
                        default='wordpress', help='Mysql User')
    parser.add_argument('--mysql-database', dest='mysql_database', type=str,
                        default='wordpress', help='Mysql database name')
    parser.add_argument('--mysql-root-password', dest='mysql_root_password', type=str,
                        default='root', help='Mysql Root Password')
    parser.add_argument('--wp-db-table-prefix', dest='wordpress_db_table_prefix', type=str,
                        default='', help='Wordpress db table prefix. If you load from a .sql file that prefix will be used')
    parser.add_argument('--plugin-repo', dest='plugin_repo_path', type=str,
                        default='', help='A local or remote Git repo for wp-content')
    parser.add_argument('--wp-known-user-email', dest='wp_known_user_email', type=str,
                        default='mail@example.com', help='wp_known_user_email')
    parser.add_argument('--wp-known-user-password', dest='wp_known_user_password', type=str,
                        default='password', help='wp_known_user_password')
    parser.add_argument('--wp-known-user-name', dest='wp_known_user_name', type=str,
                        default='cuser', help='wp_known_user_name')
    parser.add_argument('--wp-active-plugins', dest='wp_active_plugins', type=str,
                        default='', help='comma-separated list of active plugins (make sure your wp-content contains those!)')

    return parser


def print_version():
    print("container_from_sqldump v1.0")


def print_done():
    print(u'\u2713 Done.')


def perform_preflight_checks():
    platform = sys.platform
    print('performing preflight checks')
    if platform not in ('linux', 'linux2', 'darwin'):
        print('cannot run on Win32')
        return False
    if not is_successful('command -v docker'):
        print('docker binary not found.')
        return False
    if platform == 'darwin' and not is_successful('command -v docker-machine'):
        print('docker-machine binary not found.')
        return False
    print_done()
    return True


def perform_input_validation(args):
    print('performing input validation checks...')
    if not isfile(realpath(args.dump_file)):
        print("{0} is not a file".format(args.dump_file))
        return False
    print_done()
    return True


def maybe_start_docker_machine():
    platform = sys.platform
    if platform == 'darwin':
        run('docker-machine start')
        result = {}
        env_ = run('docker-machine env')
        for line in run('docker-machine env').stdout.decode('utf-8').split('\n'):
            if 'export' in line:
                parts = line.replace('export', '').strip().split('=')
            if len(parts) == 2:
                result[parts[0]] = parts[1].replace('"', '')
        os.environ.update(result)


def add_plugin_repo(plugin_repo_path, container_dir, copy_repo=True):
    if plugin_repo_path.startswith('http'):
        print('No remote repo handling yet! try a local one :)')
        return 0
    elif isdir(realpath(plugin_repo_path)):
        # symbolic link this or copy depending on preference
        if copy_repo:
            if isdir('{0}/content/'.format(container_dir)):
                run('rm -rf {0}/content/'.format(sh_quote(container_dir)))
            run('cp -r {0}/ {1}/content/'.format(sh_quote(realpath(plugin_repo_path)), sh_quote(container_dir)))
            run('chmod -R 0777 {0}/content'.format(sh_quote(container_dir)))
        else:
            run('ln -sfF {0}/ {1}/content/'.format(sh_quote(realpath(plugin_repo_path)), sh_quote(container_dir)))


def wait_for_mysql_to_boot(mysql_docker_container):
    print('waiting for MariaDB server to finish booting')
    sleep(10)

    for i in range(60):
        r = run('docker logs {0}'.format(mysql_docker_container))
        res = r.stdout.decode('utf-8')
        if 'MySQL init process done. Ready for start up' in res:
            return True

        sleep(2)
    return False


def create_folder_structure(container_dir, dump_file):
    if not isdir(container_dir):
        run('mkdir -p {0}'.format(container_dir))

    run('mkdir -p {0}/tmp/mysql'.format(sh_quote(container_dir)))
    run('mkdir -p {0}/content'.format(sh_quote(container_dir)))
    run('mkdir -p {0}/tmp/dump'.format(sh_quote(container_dir)))
    run('mkdir -p {0}/tmp/sql_scripts'.format(sh_quote(container_dir)))
    run('mkdir -p {0}/tmp/setup_scripts'.format(sh_quote(container_dir)))

    run("cp -f {0} {1}/tmp/dump/seed.sql".format(sh_quote(realpath(dump_file)), sh_quote(container_dir)))
    run('rm -rf {0}/tmp/setup_scripts/'.format(sh_quote(container_dir)))
    run("cp -rf {0}/ {1}/tmp/setup_scripts/".format(sh_quote(realpath(join(ROOT_PATH, 'setup_scripts'))), sh_quote(container_dir)))

    run('chmod -R 0777 {0}/tmp'.format(sh_quote(container_dir)))


def main(args):
    args = build_arg_parser().parse_args(args)
    mysql_expose_port = 6603
    php_version = '7.1'
    container_name = args.container_name
    dump_file = args.dump_file
    mysql_user = args.mysql_user
    mysql_password = args.mysql_password
    mysql_database = args.mysql_database
    mysql_root_password = args.mysql_root_password
    wordpress_db_table_prefix = args.wordpress_db_table_prefix

    plugin_repo_path = args.plugin_repo_path

    wp_active_plugins = args.wp_active_plugins
    wp_known_user_password = args.wp_known_user_password
    wp_known_user_name = args.wp_known_user_name
    wp_known_user_email = args.wp_known_user_email

    print_version()

    if not perform_preflight_checks():
        return 1
    if not perform_input_validation(args):
        return 1

    relative_container_dir = join('registered_containers', container_name)
    container_dir = realpath(join(ROOT_PATH, relative_container_dir))

    sh_quote = shlex.quote

    create_folder_structure(container_dir, dump_file)

    tpl_args = {
        'mysql_database': mysql_database,
        'mysql_user': mysql_user,
        'mysql_password': mysql_password,
        'mysql_root_password': mysql_root_password,
        'wordpress_db_table_prefix': wordpress_db_table_prefix,
        'mysql_expose_port': mysql_expose_port
    }

    mysql_docker_container = '{0}_mysql'.format(container_name)
    wordpress_docker_container = '{0}_wordpress'.format(container_name)

    tpl = ' '.join((
        'docker run',
        '--name {0}'.format(mysql_docker_container),
        '--restart always',
        '-e "MYSQL_ROOT_PASSWORD={mysql_root_password}" -e "MYSQL_USER={mysql_user}" -e "MYSQL_PASSWORD={mysql_password}" -e "MYSQL_DATABASE={mysql_database}" '.format(**tpl_args),
        '-p {0}:3306 '.format(mysql_expose_port),
        "-v {0}/tmp/sql_scripts:/sql_scripts ".format(container_dir),
        "-v {0}/tmp/dump:/dump ".format(container_dir),
        "-v {0}/tmp/setup_scripts:/setup_scripts ".format(container_dir),
        '-d mariadb:latest',
        '--bind-address=*'
    ))

    if plugin_repo_path:
        add_plugin_repo(plugin_repo_path, container_dir)

    maybe_start_docker_machine()

    docker_machine_ip = run('docker-machine ip').stdout.strip().decode('utf-8')
    print(docker_machine_ip)

    run('docker rm -fv {0}'.format(mysql_docker_container))

    run(tpl, debug=True)

    r = run('docker ps')


    print('waiting for MariaDB server to finish booting')
    sleep(10)

    mysql_init_process_done = wait_for_mysql_to_boot(mysql_docker_container)
    if not mysql_init_process_done:
        print('MySQL init process not done. Exiting')
        return 0
    print('Done! Connect with `mysql -h {0} -P {1} -uwordpress -pwordpress wordpress`'.format(docker_machine_ip, mysql_expose_port))


    if isfile(realpath(dump_file)):
        cmd = ''.join(['docker run -it --link sensei_wp_instance:mysql --rm mariadb sh -c \'',
            'exec mysql -h"$MYSQL_PORT_3306_TCP_ADDR" -P"$MYSQL_PORT_3306_TCP_PORT" -uroot -p"$MYSQL_ENV_MYSQL_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS wordpress"\''
        ])
        run(cmd)

        cmd = ''.join(['docker run -it -v {0}/tmp/dump:/dump --link {1}:mysql --rm mariadb sh -c '
            '\'exec mysql -h"$MYSQL_PORT_3306_TCP_ADDR" -P"$MYSQL_PORT_3306_TCP_PORT" -uroot -p"$MYSQL_ENV_MYSQL_ROOT_PASSWORD" wordpress < /dump/seed.sql\''.format(container_dir, mysql_docker_container)
        ])
        run(cmd)

        cmd = ''.join(['docker run -it -v {0}/tmp/dump:/dump -v {0}/tmp/setup_scripts:/setup_scripts --link {1}:mysql --rm mariadb sh -c '
            '\'exec mysql -h"$MYSQL_PORT_3306_TCP_ADDR" -P"$MYSQL_PORT_3306_TCP_PORT" -uroot -p"$MYSQL_ENV_MYSQL_ROOT_PASSWORD" wordpress < /setup_scripts/add_known_admin.sql\''.format(container_dir, mysql_docker_container)
        ])
        run(cmd)

        mysql_engine = create_engine(
            'mysql+pymysql://{user}:{password}@{host}:{port}/{dbname}'.format(
                user=mysql_user, password=mysql_password, host=docker_machine_ip,
                dbname=mysql_database, port=mysql_expose_port)
        )

        r = mysql_engine.execute('show tables')
        tables = []
        wordpress_db_table_prefix = 'wp_'

        for row in r.fetchall():
            if len(row) > 0:
                tablename = row[0]
                tables.append(tablename)

                if 'users' in tablename:
                    wordpress_db_table_prefix = tablename.split('users')[0]

        print('WordPress db prefix is %s' % wordpress_db_table_prefix)
        print('Adding Known admin user')

        import hashlib
        users_table = '{0}users'.format(wordpress_db_table_prefix)
        usermeta_table = '{0}usermeta'.format(wordpress_db_table_prefix)
        user_email = wp_known_user_email
        user_login = wp_known_user_name
        user_pass = wp_known_user_password.encode('utf8')

        sql = """\
    INSERT INTO `{users_table}`
        (`user_login`, `user_pass`, `user_nicename`,
         `user_email`, `user_url`, `user_registered`,
         `user_activation_key`, `user_status`, `display_name`)
    VALUES
        ('{user_login}', '{user_pass}', '{user_nicename}', '{user_email}',
         'http://www.test.com/', '2011-06-07 00:00:00', '', '0', '{user_nicename}');""".format(
            users_table=users_table,
            user_login=user_login,
            user_pass=hashlib.md5(user_pass).hexdigest(),
            user_email=user_email,
            user_nicename=user_login
        )
        print(sql)

        r = mysql_engine.execute(sql)

        r = mysql_engine.execute("SELECT ID from {users_table} WHERE user_email='{user_email}' LIMIT 1".format(users_table=users_table, user_email=user_email))
        user_id = None
        for row in r.fetchall():
            user_id = row[0]

        if user_id is None:
            print('No user inserted. Exiting')
            return 0

        print('User %s added' % user_id)

        meta = {
            '{0}capabilities'.format(wordpress_db_table_prefix): 'a:1:{s:13:"administrator";s:1:"1";}',
            '{0}user_level'.format(wordpress_db_table_prefix): 10
        }

        for meta_key, meta_value in meta.items():
            sql = "INSERT INTO {usermeta_table} (`umeta_id`, `user_id`, `meta_key`, `meta_value`) VALUES (NULL, '{u_id}', '{meta_key}', '{meta_value}');".format(
                usermeta_table=usermeta_table, u_id=user_id, meta_key=meta_key, meta_value=meta_value)
            mysql_engine.execute(sql)
            print(sql)

        sql = "UPDATE {wordpress_db_table_prefix}options SET option_value = '' WHERE option_name = 'active_plugins';".format(wordpress_db_table_prefix=wordpress_db_table_prefix)
        mysql_engine.execute(sql)
        print(sql)

        sql = "SELECT option_value FROM {wordpress_db_table_prefix}options WHERE option_name = 'home' OR option_name = 'siteurl';".format(wordpress_db_table_prefix=wordpress_db_table_prefix)
        r = mysql_engine.execute(sql)
        guid = None
        for res in r:
            guid = res[0]
        if guid is None:
            print('guid is empty')
            return;
        print(guid)
        # return 0

        sql = "UPDATE {wordpress_db_table_prefix}options SET option_value = 'http://{host}:{port}' WHERE option_name = 'home' OR option_name = 'siteurl'"\
            .format(host=docker_machine_ip, port='8080', wordpress_db_table_prefix=wordpress_db_table_prefix)
        mysql_engine.execute(sql)
        print(sql)

        # a:2:{i:0;s:43:"sensei-content-drip/sensei-content-drip.php";i:1;s:37:"woothemes-sensei/woothemes-sensei.php";}
        active_plugins_serialized = phpserialize.dumps(wp_active_plugins.split(',')).decode('utf-8')
        sql = "UPDATE {wordpress_db_table_prefix}options SET option_value = '{active_plugins_serialized}' WHERE option_name = 'active_plugins';"\
            .format(wordpress_db_table_prefix=wordpress_db_table_prefix, active_plugins_serialized=active_plugins_serialized)
        mysql_engine.execute(sql)
        print(sql)

        new_url = 'http://{0}:8080'.format(docker_machine_ip)

        sql = "UPDATE  {wordpress_db_table_prefix}posts SET guid = replace(guid, '{old_url}', '{new_url}');".format(wordpress_db_table_prefix=wordpress_db_table_prefix, new_url=new_url, old_url=guid)
        mysql_engine.execute(sql)
        print(sql)

        sql = "UPDATE {wordpress_db_table_prefix}posts SET post_content = replace(post_content, '{old_url}', '{new_url}');"\
            .format(wordpress_db_table_prefix=wordpress_db_table_prefix, new_url=new_url, old_url=guid)
        mysql_engine.execute(sql)
        print(sql)

        sql = "UPDATE {wordpress_db_table_prefix}options SET option_value = 'twentysixteen' WHERE option_name IN ('template', 'stylesheet')"\
            .format(host=docker_machine_ip, port='8080', wordpress_db_table_prefix=wordpress_db_table_prefix)
        mysql_engine.execute(sql)
        print(sql)

    run('docker rm -fv {0}'.format(wordpress_docker_container))

    tpl_args['wordpress_db_table_prefix'] = wordpress_db_table_prefix

    wordpress_docker_run_tpl = ' '.join((
        'docker run',
        '--name {0}'.format(wordpress_docker_container),
        '--link {0}:mysql'.format(mysql_docker_container),
        '--restart always',
        '-e "WORDPRESS_TABLE_PREFIX={wordpress_db_table_prefix}" -e "WORDPRESS_DB_USER={mysql_user}" -e "WORDPRESS_DB_PASSWORD={mysql_password}" -e "WORDPRESS_DB_NAME={mysql_database}" '\
            .format(**tpl_args),
        '-p 8080:80 '.format(mysql_expose_port),
        "-v {0}/content:/var/www/html/wp-content".format(container_dir),
        '-d wordpress:4.6.1-php7.0-apache'
    ))

    print(wordpress_docker_run_tpl)
    run(wordpress_docker_run_tpl, debug=True)

    for i in range(10):
        sleep(2)
        r = run('docker logs {0}'.format(wordpress_docker_container))
        print(r.stdout)

    print('Done! You can access the site at http://{0}:8080'.format(docker_machine_ip))
    print('Done! Connect with `mysql -h {0} -P {1} -uwordpress -pwordpress wordpress` (wp prefix is `{2}`)'.format(docker_machine_ip, mysql_expose_port, wordpress_db_table_prefix))
    print('Attach to wp with `docker exec -i -t {0} /bin/bash`'.format(wordpress_docker_container))

    return 0


if __name__ == '__main__':
    exit(main(sys.argv[1:]))
