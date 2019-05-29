#!/bin/bash



if [ ! -d "/dump"]; then
  echo "Did not find `/dump` directory. Exiting" 1>&2;
  exit 1;
fi


mysql -u$MYSQL_USER -p$MYSQL_PASSWORD -h db $MYSQL_DATABASE < /dump/seed.sql
