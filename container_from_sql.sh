#!/usr/bin/env bash

container_from_sqldump="container_from_sqldump";

function version {
  echo "
container_from_sqldump v1.0
  "
}


function usage {
  version
  echo "Usage:

container_from_sqldump -f <sqldump_file>
    [-u <mysql_user>] [-p <mysql_pass>]
"
};

dump_file=
mysql_user="root"
mysql_pass="root"

command -v docker >/dev/null 2>&1 || {
  echo >&2 "Docker binary not found. Exiting"
  exit 1
}

if [ "$(uname)" == "Darwin" ]; then
  command -v docker-machine >/dev/null 2>&1 || {
    echo >&2 "Docker - Machine binary not found. Exiting"
    exit 1
  }
fi

if [ $# -eq 0 ]; then
  echo "No arguments supplied.";
  usage;
  exit 1;
fi

while getopts ":f:u:p:h" opt; do
  case $opt in
    f)
      dump_file=${OPTARG}
      ;;
    u)
      mysql_user=${OPTARG}
      ;;
    p)
      mysql_pass=${OPTARG}
      ;;
    h)
      usage
      exit 0
      ;;
    \?)
      echo "Invalid Option -$OPTARG" >&2
      usage
      exit 1
      ;;
    :)
      echo "Option -$OPTARG requires an argument." >&2
      usage
      exit 1;
      ;;
    esac

done
shift $((OPTIND-1))

version
echo "Creating MariaDB container with:
"
echo "* sqldump    = ${dump_file}"
echo "* mysql_user = ${mysql_user}"
echo "* mysql_pass = ${mysql_pass}"

mkdir -p tmp/{mysql,dump}

echo "cp ${dump_file} tmp/dump/"

cp $dump_file tmp/dump/

docker-machine start

eval $(docker-machine env)

docker rm -f mysql

docker run --name "${container_from_sqldump}" \
  -v $(pwd)/tmp/dump:/dump \
  -v $(pwd)/tmp/scripts:/scripts \
  -v $(pwd)/tmp/dump:/docker-entrypoint-initdb.d \
  -e MYSQL_DATABASE=wordpress \
  -e MYSQL_USER="${mysql_user}" \
  -e MYSQL_PASSWORD="${mysql_pass}" \
  -d -it pluie/alpine-mysql

echo "Mysql running! Attaching to container..."

docker exec -i -t "${container_from_sqldump}" /bin/bash
