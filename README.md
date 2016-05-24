# Automated deploy of a Ceph test environment on beaker
The aim of this project is to make configuring and setting up a skeleton
Red Hat Ceph Storage environment quickly and easily for POC deployments,
test environments and more.

## Goals
This project contains scripts which provide automated functionality for:

* Subscribing the selected machines to Red Hat `subscription-manager`.
* Editing the `ceph-ansible` playbooks with the desired functionality.
* Deploying a Ceph cluster using the edited playbook(s).

## Prerequisites
Install:
* ansible
* python
* Run the following to install the required python libraries:
~~~
$ sudo pip install -r extras/requirements.txt
~~~

## Usage
**Note**: Currently, `deploy.py` only supports deployments of mons and osds,
support for other Ceph components will arrive later.

The deploy script deploys test environments for Ceph inside of beaker by
piggybacking off of ceph-ansible playbooks.

On first run, the script will generate a config file in `extras/deploy.cfg`
which contains subscription-manager username, password and root password
information.  A configuration file is used for this step as often these variables
do not change across deployments, or change much less frequently.

The `deploy.py` script **requires** the following flags:
* `-m MONS, --mons MONS`: Define comma-delimited FQDNs where ceph-mons should be
configured. (Ex. ceph2.example.com,ceph3.example.com)
* `-o OSDS, --osds OSDS`: Define comma-delimited FQDNs where ceph-osds should be
configured. (Ex. ceph2.example.com,ceph3.example.com)
* `-d DIRECTORY, --ansible-directory DIRECTORY`: Specify the location the
ceph-ansible directory resides. It's best to utilize a secondary ceph-ansible
directory as the script may clobber pre-existing settings.

The script also accepts the following **optional** flags:
* `--no-ansible`: Skip automated Ansible playbook editing. This option provides
users the ability to manually edit their own playbooks while still maintaining
the ability to perform Ansible prerequisites and playbook running via this
script OR to use a previously edited playbook for a new deployment.
* `-j OSD_JOURNAL_SIZE, --journal-size OSD_JOURNAL_SIZE`: Specify the size in MB
to be used when creating the OSD journal during initial OSD setup. If no size is
specified it will be calculated from one of the OSD hosts supplied.
* `-c CLUSTER_NETWORK, --cluster-network CLUSTER_NETWORK`: Specify the cluster
network address in CIDR notation to be used for back-end cluster communication.
If none is supplied and the host(s) selected have more then one interface the
cluster and public networks will be selected automatically.
If the host(s) only have one network, only a public network will be configured.
* `-p PUBLIC_NETWORK, --public-network PUBLIC_NETWORK`: Specify the public
network address in CIDR notation to be used for public, front-end cluster
communication. If none is supplied and the host(s) selected have more
then one interface the cluster and public networks
will be selected automatically.
* `--disable-cephx`: Do not enable cephx authentication.


## Examples
To deploy a cluster with 2 mons and 3 osd hosts:
~~~
$ ./deploy.py -m ceph1.hq.gsslab.rdu.redhat.com,ceph2.hq.gsslab.rdu.redhat.com -o ceph3.hq.gsslab.rdu.redhat.com,ceph4.hq.gsslab.rdu.redhat.com,ceph5.hq.gsslab.rdu.redhat.com -d ~/ceph-ansible
~~~

To deploy a cluster with 1 mon and 1 osd host when the hosts are either already
reserved in beaker or the users' personal machines:
~~~
$ ./deploy.py -m foobar1.example.com -o foobar2.example.com -d ~/ceph-ansible --no-beaker
~~~

## TODOs
* Provide better error handling to all functions
* Implement logging
* Support other ceph component installations
* Support expansion of existing cluster installations
