# Container From Sqldump

Spin a MariaDB docker container, populate it with a WordPress database dump .sql file.
Then massage database contents for local development (e.g. changing `guids`, `siteurl`, adding a known user)

Additionally, start a WP container that uses that db

Setup/Usage

    virtualenv --python=python3 env
    env/bin/pip install -r requirements.txt
    env/bin/python main.py --help
    env/bin/python main.py example_wp_instance <some mysqldump>.sql --plugin-repo <repo>

Another example, demonstrating usage of various switches

    env/bin/python main.py sensei_wp_instance \
      /tmp/example.com.staging.sql \
      --plugin-repo /var/www/example.com/content \
      --wp-active-plugins='sensei-content-drip/sensei-content-drip.php,woothemes-sensei/woothemes-sensei.php,woocommerce/woocommerce.php' \
      --wp-known-user-email='foo@bar.com' \
      --wp-known-user-password='1223fh;ha' \
      --wp-known-user-name='foo'
