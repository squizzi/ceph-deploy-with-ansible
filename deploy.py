#!/usr/bin/env python
import sys
import paramiko
import os
import logging
import argparse
import getpass
import re
import ansible.runner
import ansible.playbook
import time
from ansible import callbacks, utils
from ansible.inventory import Inventory
from colored import fore, back, style
from IPy import IP
from subprocess import Popen, call, CalledProcessError, check_output, PIPE, STDOUT
from progress.spinner import Spinner
from bs4 import BeautifulSoup

""" Provide parser validation """
def is_valid_hostname(hostname):
    if len(hostname) > 255:
        return False
    if hostname[-1] == ".":
        hostname = hostname[:-1]
    allowed = re.compile("(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(x) for x in hostname.split("."))


""" Check to ensure the package prerequisites exist """
def packages_satisfied():
    # TODO: Don't use print, use logging here instead
    if os.path.isfile('/usr/bin/ansible') == False:
        print "deploy.py: error: ansible is not installed.  Install it before \
        continuing."
        exit(1)
    if os.path.isfile('/usr/bin/bkr') == False:
        print "deploy.py: error: the bkr cli is not installed.  Install it before \
        continuing."
        exit(1)

""" Configuration file creation and variables """
# We need to create an empty inventory file to satisfy the inventory variable
def create_ansiblehosts():
    if os.path.isfile('ansible_hosts') == False:
        f = open('ansible_hosts', 'w')
        f.write("")
    ansibleInventory = Inventory(host_list='ansible_hosts')

""" On first run generate a config file """
def save_config(filename, option, value):
    # If the value is an array, we'll need to convert it to a string
    if type(value) is list:
        new_value = ""
        for sub_value in value:
            if new_value == "":
                new_value = sub_value
            else:
                new_value = sub_value + "," + new_value
                value = new_value
    config = open(filename, "a")
    config.write(option + "=" + value + "\n")
    config.close()

def load_config(filename):
    configs = {}
    # Open config file and read in values (if it exists)
    if os.path.exists(filename):
        config = open(filename, "r")
        content = config.read()
        lines = content.split("\n")
        for data in lines:
            # If the line returned from the config file is
            # trying to set a value, load it up and set it in
            # our configs dictionary
            if data.find("=") != -1:
                option = data.split("=")[0]
                value = data.split("=")[1]
                # if the value has a comma in it, we need
                # to build an array instead of a string
                if value.find(",") != -1:
                    value = value.split(",")
                configs[option] = value
    return configs

# Ask questions to build user's configuration
# type_ should be either 'string' or 'array'
def question(type_,question = None):
    # If no type_ is specified, the first arg becomes the question
    # and a string value is assumed
    if question == None:
        question = type_
        type_ = "string"
    answer = None
    while not answer:
        answer = raw_input(question + ": ")
    # If this is an array, we need to convert from string to array
    if type_ == "array":
        # Remove spaces
        answer = answer.replace(" ","")
        answer = answer.split(",")
    return answer

""" Generate Ansible Prerequisites """
def generate_prereqs():
    beaker_hosts = args.mons + "," + args.osds
    beaker_host_list = set(beaker_hosts.split(","))
    # Create the ansible inventory hosts file
    print (fore.LIGHT_BLUE + style.BOLD + "\nCreating ansible inventory" +
    style.RESET)
    print "Writing hostnames out to ansible-hosts file"

    f = open('ansible_hosts', 'w')
    f.write('[mons] \n')
    for each in mon_list:
        f.write(each)
        f.write('\n')
    f.write('[osds] \n')
    for each in osd_list:
        f.write(each)
        f.write('\n')
    f.close()
    #TODO: Add rgw, restapi support to inventory creation.

    # Wipe specific lines for each host in the known_hosts file to prevent remote
    # host identification failures from breaking script progress
    print "Removing re-used hosts from the .ssh/known_hosts file to prevent host key verification failures"
    host_list = mon_list + osd_list
    homedir = os.path.expanduser('~')
    # Rename the existing known_hosts file
    os.rename("%s/.ssh/known_hosts" % (homedir), "%s/.ssh/known_hosts_old" % (homedir) )
    # Write a new known_hosts file without any of the targetted hostnames for
    # this run
    with open("%s/.ssh/known_hosts_old" % (homedir), "r" ) as sshfile_input:
        with open("%s/.ssh/known_hosts" % (homedir), "wb" ) as sshfile_output:
            for line in sshfile_input:
                if not line.startswith(tuple(beaker_host_list)):
                    sshfile_output.write(line)

    # Generate keyless ssh for the playbook to run
    print (fore.LIGHT_BLUE + style.BOLD + "\nGenerating keyless ssh for the root user on each host." + style.RESET)

    # Check to make sure the user has an id_rsa.pub file before continuing
    if os.path.isfile('%s/.ssh/id_rsa.pub' % (homedir) ) == False:
        # For now we'll just prompt the user to run ssh-keygen on their own.  We
        # can probably use the Crypto library in the future to do this for users
        # but that's a can of worms
        print (fore.RED + "No /.ssh/id_rsa.pub file found in home directory \
        please create one using ssh-keygen and restart this script")
        exit(1)
    else:
        pass

    for each in beaker_host_list:
        ssh_deploy_key_args = [ 'ssh-deploy-key',
                    '-u', 'root',
                    '-p', '%s' % (beakerPassword),
                    '%s' % (each) ]
        ssh_deploy_key = Popen(ssh_deploy_key_args)
        ssh_deploy_key.wait()
    #TODO: Need error handling, if we raise a 'CONNECTION FAILURE' we need to
    ## exit and log it

""" Beaker reservation """
def beaker_reserve():
    # Grab a kerberos ticket
    print (fore.LIGHT_BLUE + style.BOLD + "\nRequesting a kerberos ticket for beaker use." + style.RESET)
    if call(['klist', '-s']) == 0:
        print "User already has a valid ticket, continuing."
        pass
    else:
        # TODO: What if the user gives us a wrong password? We keep on trucking if
        ## so; that needs to be corrected.
        password = getpass.getpass('Enter the password for your kerberos user: ')
        kinit = '/usr/bin/kinit'
        kinit = Popen(kinit, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        kinit.stdin.write('%s\n' % password)
        kinit.wait()
        # FIXME: this doesn't work quite right, will have to revisit error
        ## handling wrong passwords and other kinit failures
        ## try:
        ##    output = check_output('/usr/bin/kinit')
        ##    returncode = 0
        ## except CalledProcessError as e:
        ##    output = e.output
        ##    print e.output
        ##    exit(1)

    # Reserve the machines specified in -m and -o in bkr and watch the jobs for
    # completion
    print (fore.LIGHT_BLUE + style.BOLD + "\nReserving the requested mons and osds in beaker and configuring them for use with Ceph" + style.RESET)
    job_id_list = []

    for each in beaker_host_list:
        bkr_args = [ '/usr/bin/bkr', "workflow-simple",
                  "--family", "RedHatEnterpriseLinux7",
                  "--variant", "Server",
                  "--arch", "x86_64",
                  "--task", "/distribution/reservesys",
                  "--ks-meta='autopart_type=plain'",
                  "--machine", "%s" % each ]
        bkr = Popen(bkr_args, stdout=PIPE, stderr=STDOUT)
        #FIXME: If job_id contains an Exception exit properly
        job_id = bkr.stdout.read()
        regex = "[0-9]+"
        job_id_edited = re.findall(regex, job_id)
        #FIXME: Need proper error handling during kinit but this is a crappy
        # workaround for now.
        try:
            print "Created a new job: " + job_id_edited[0]
        except IndexError:
            print (fore.RED + 'deploy.py: IndexError: kinit may have failed. Check klist to ensure a kerberos ticket was properly created'
            + style.RESET)
            exit(1)
        else:
            job_id_list.append(job_id_edited[0])
            bkr.wait()

    print (fore.LIGHT_BLUE + style.BOLD + "\nWatching the jobs and waiting for a completed status. This process may take a while to complete." + fore.RED
    + style.BOLD + " Do not interrupt the script!" + style.RESET)
    for each in job_id_list:
        each = "J:" + each
        bkr_args = [ "/usr/bin/bkr", "job-results", "%s" % (each) ]
        # Query job-results every 30 seconds for a Completed status
        while True:
            bkr_watch = Popen(bkr_args, stdout=PIPE)
            b = BeautifulSoup(bkr_watch.stdout.read())
            time.sleep(30)
            if b.task["status"] == 'Completed':
                break
            if b.task["status"] == 'Fail' or 'Failed':
                print (fore.RED + style.BOLD + "The beaker job has failed." + style.RESET + style.BOLD + "Please check the status of each job at https://beaker.engineering.redhat.com/jobs/ then re-run the script." + style.RESET)
                exit(1)
            if b.task["status"] != 'Completed':
                print 'Checking job status for %s again in 30 seconds...' % each

""" Make sure we can access the hosts in the inventory via the ansible ping
module """
def ansible_ping():
    print (fore.LIGHT_BLUE + style.BOLD + "\nContacting the hosts using the ansible ping module" + style.RESET)
    runner = ansible.runner.Runner(
        module_name='ping',
        module_args='',
        pattern='*',
        inventory=ansibleInventory,
        remote_user='root'
        )
    if "'failed': True" in str(runner.run()):
        print (fore.RED + "One or more of the hosts failed to respond to the ping")
        print runner.run()
        exit(1)
    else:
        print (fore.GREEN + "Success" + style.RESET)
        pass

""" Subscribe hosts to correct repos using subscription-manager """
def subscribe_hosts():
    # ssh to the hosts and subscribe them to the Employee SKU in subscription-manager
    print (fore.LIGHT_BLUE + style.BOLD + "\nContacting the hosts and registering them using subscription-manager" + style.RESET)
    registerHosts = "subscription-manager register --username=%s --password=%s ; subscription-manager attach --pool=8a85f9833e1404a9013e3cddf95a0599 ; subscription-manager repos --disable=*" % (subscriptionUsername, subscriptionPassword)
    for each in beaker_host_list:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(each,
                    username="root",
                    password=beakerPassword,
                    look_for_keys=False
                    )
        stdin, stdout, stderr = ssh.exec_command(registerHosts)



""" Ansible playbook editing """
def build_playbook():
    # Generate the variables for configuration replacements
    print (fore.LIGHT_BLUE + style.BOLD + "\nEditing Ansible playbook located in the %s directory" % (args.directory) + style.RESET )
    # Determine what size the OSD journal should be if -j isn't supplied
    if args.osd_journal_size == False:
        # No value provided, so create one based on host device size
        print "No osd journal size provided.  Generating one based on disk size on one of the provided osd hosts"
        # Connect to one of the osd hosts and pull the largest disk size.
        # FIXME: We're making a big assumption here that the disk sizes will all
        # be similar enough across the osds, we'll probably want to fix this in
        # the future.
        lsblk_osd = "lsblk --output SIZE | grep 'G' | sort | head -1"
        ssh.connect(osd_list[0],
                    username="root",
                    password=beakerPassword,
                    look_for_keys=False
                    )
        stdin, stdout, stderr = ssh.exec_command(lsblk_osd)
        # The output we receive is in GB
        output = stdout.read()
        regex = "[0-9]+"
        # Redefine output with only numbers and perform the calculation to
        # determine 1% of the size, set that as args.osd_journal_size
        output = re.findall(regex, output)
        journal_size_mb = int(output[0]) * 1024 * 0.01
        args.osd_journal_size = int(round(journal_size_mb,1))
    else:
        print "osd journal size provided, skipping automatic detection"
        # Verify an actual number was passed in for the variable and pass it in
        # if so
        try:
            args.osd_journal_size = int
        except ValueError:
            print(fore.RED + "deploy.py: ValueError: An integer value was not provided for osd journal size (-j)")

    # Determine public network to use
    if args.public_network == False:
        print "Automated public network IP detection is not functional in this release, please re-run the script with the -p and --no-beaker flags."
        exit(1)
        # No value provided, so create one based on host addresses
        # We can ssh to one of the machines here and assume all of the hosts
        # are on the same network and can communicate with each other
        #stdin, stdout, stderr = ssh.exec_command("ip route")
        #output = stdout.read()

    else:
        print "Public network IP provided, skipping automatic detection"
        # Confirm the user inputted an IP in CIDR notation then pass in the value
        try:
            IP(args.public_network)
        except ValueError:
            print(fore.RED + "deploy.py: ValueError: IP Address format was invalid for public network" + style.RESET )
            raise

    # Determine cluster network to use
    if args.cluster_network == False:
        print "Automated cluster network IP detection is not functional in this release. \
        Reverting to public network value provided.  If you would like to specify a cluster network, please re-run the script with the -c and --no-beaker flags."
        args.cluster_network = "{{ public_network }}"

        # No value provided, so create one based on host addresses

        # Host only has one IP so default back to public network

    else:
        print "Cluster network IP provided, skipping automatic detection"
        # Confirm the user inputted an IP in CIDR notation then pass in the value
        try:
            IP(args.cluster_network)
        except ValueError:
            print(fore.RED + "deploy.py: ValueError: IP Address format was invalid for cluster network" + style.RESET )
            raise

    # cephx true or false
    if args.disable_cephx == True:
        cephx_ = "false"
    else:
        cephx_ = "true"

    infile = open('%s/group_vars/all.sample' % (args.directory))
    outfile = open('%s/group_vars/all' % (args.directory), 'w')
    replacements = { # Enable RHCS with download from cdn
                    '#ceph_stable_rh_storage: false':'ceph_stable_rh_storage: true',
                    '#ceph_stable_rh_storage_cdn_install: false':'ceph_stable_rh_storage_cdn_install: true',
                     # Specify a OSD journal size, and use the journal size
                     # from args.osd_journal_size if provided
                     '#journal_size: 0':'journal_size: %s' % (args.osd_journal_size),
                     # Specify public/private networks to use
                     '#public_network: 0.0.0.0/0':'public_network: %s' % (args.public_network),
                     '#cluster_network: "{{ public_network }}"':'cluster_network: %s' % (args.cluster_network),
                     # Enable or disable cephx
                     '#cephx: true':'cephx: %s' % (cephx_)
                     }

    for line in infile:
    	for src, target in replacements.iteritems():
    		line = line.replace(src, target)
    	outfile.write(line)
    infile.close()
    outfile.close()

    # Perform the same thing for group_vars/osds
    infile = open('%s/group_vars/osds.sample' % (args.directory))
    outfile = open('%s/group_vars/osds' % (args.directory), 'w')
    replacements = { # Enable or disable cephx
                    '#cephx: true':'cephx: %s' % (cephx_),
                     # Activate the fsid variable since these are baremetal
                    '#fsid: "{{ cluster_uuid.stdout }}"':'fsid: "{{ cluster_uuid.stdout }}"',
                     # Set OSD auto discovery
                    '#osd_auto_discovery: false':'osd_auto_discovery: true',
                     # Enable journal colocation
                    '#journal_collocation: false':'journal_collocation: true'
                     }

    for line in infile:
    	for src, target in replacements.iteritems():
    		line = line.replace(src, target)
    	outfile.write(line)
    infile.close()
    outfile.close()

""" Ansible deploy """
# Run the playbook
def run_playbook():
    # Reference the correct site.yml
    ansiblePlaybook = "%s/site.yml" % (args.directory)
    ansible_run = [ '/usr/bin/ansible',
              "ansible-playbook",
              "-vvvv",
              "--user=root",
              "-i", "ansible_hosts",
              "%s" % ansiblePlaybook ]
    ansible_run_ = Popen(bkr_args, stdout=PIPE, stderr=STDOUT)
    ansible_run_.wait()

def main():
    # Define globals
    global args, inventory, mon_list, osd_list, beaker_hosts, beaker_host_list
    global ansibleInventory, beakerPassword, subscriptionUsername, subscriptionPassword

    # Provide command line arguments
    parser = argparse.ArgumentParser(description="Deploy test environments for Ceph \
                                    inside of beaker by piggybacking off of \
                                    ceph-ansible playbooks.")
    parser.add_argument("-m",
                        "--mons",
                        required=True,
                        dest="mons",
                        help="Define comma-delimited FQDNs where ceph-mons should \
                        be configured.  (Ex. ceph2.example.com,ceph3.example.com)")
    parser.add_argument("-o",
                        "--osds",
                        required=True,
                        dest="osds",
                        help="Define comma-delimited FQDNs where ceph-osds should \
                        be configured. (Ex. ceph2.example.com,ceph3.example.com)")
    #FIXME: Disabled until we add the required setup tasks for this option
    #parser.add_argument("-r",
    #                    "--rgws",
    #                    dest="rgws",
    #                    help="Define comma-delimited FQDNs where a radosgw should \
    #                    be configured. (Ex. ceph2.example.com,ceph3.example.com)")
    parser.add_argument("-d",
                        "--ansible-directory",
                        #FIXME: 'required = True' should not be set when
                        # '--no-ansible' is used.
                        required = True,
                        dest="directory",
                        help="Specify the location the ceph-ansible directory \
                        resides.  It's best to utilize a secondary ceph-ansible \
                        directory as the script may clobber pre-existing settings.")
    parser.add_argument("--no-ansible",
                        action="store_true",
                        dest="no_ansible",
                        help="Skip automated Ansible playbook editing. This option \
                        provides users the ability to manually edit their own \
                        playbooks while still maintaining the ability to perform \
                        Ansible prerequisites and playbook running via this script. \
                        OR to use a previously edited playbook for a new deployment.")
    parser.add_argument("--no-beaker",
                        action="store_true",
                        dest="no_beaker",
                        help="Do not attempt to reserve the provided host names in \
                        beaker. This option should only be used if the hosts are \
                        either not beaker machines OR have previously been reserved in \
                        beaker using a different method.")
    parser.add_argument("-j",
                        "--journal-size",
                        dest="osd_journal_size",
                        help="Specify the size in MB to be used when creating the \
                        OSD journal during initial OSD setup.  If no size is \
                        specified it will be calculated from one of the OSD hosts \
                        supplied.")
    parser.add_argument("-c",
                        "--cluster-network",
                        dest="cluster_network",
                        # TODO: Will require for now until automated detection
                        # is implemented.
                        help="Specify the cluster network address in CIDR notation \
                        to be used for back-end cluster communication.  If none is \
                        supplied and the host(s) selected have more then one \
                        interface the cluster and public networks will be selected \
                        automatically (not functional in this release, this flag is required). If the host(s) only have one network, only \
                        a public network will be configured.")
    parser.add_argument("-p",
                        "--public-network",
                        dest="public_network",
                        # TODO: Will require for now until automated detection
                        # is implemented.
                        required=True,
                        help="Specify the public network address in CIDR notation \
                        to be used for public, front-end  cluster communication.  \
                        If none is supplied and the host(s) selected have more \
                        then one interface the cluster and public networks will be \
                        selected automatically. (not functional in this release, this flag is required).")
    parser.add_argument("--disable-cephx",
                        action="store_true",
                        dest="disable_cephx",
                        help="Do not enable cephx authentication.")
    #TODO: add expansion arguments to support in place cluster expansions.
    ## Most likely, we'll need to negate the required=True for mons/osds and make
    ## only one required.

    args = parser.parse_args()

    # Verify FQDNs have been passed to -m, -o
    mon_list = args.mons.split(",")
    osd_list = args.osds.split(",")
    beaker_hosts = args.mons + "," + args.osds
    beaker_host_list = set(beaker_hosts.split(","))
    for each in beaker_host_list:
        if is_valid_hostname(each) == False:
            print (fore.RED + "deploy.py: Error: The provided host: %s does not appear to be a valid FQDN or IP address." % each)
            exit(1)

    # Build localized config if it doesn't exist
    """ Build a local config for some user secrets """
    config_file = "extras/deploy.cfg"
    config = load_config(config_file)

    # Config file variables
    # subscription-manager username
    if not ("subscriptionUsername" and "subscriptionPassword" and "beakerPassword" in config) or not (os.path.isfile('extras/deploy.cfg')):
        print (fore.LIGHT_BLUE + style.BOLD + "Detected that some configuration variables may not exist in the extras/deploy.cfg file, creating them now."
        + style.RESET)

    if not "subscriptionUsername" in config:
        subscriptionUsername = question("string","Enter subscription-manager username")
        save_config(config_file, "subscriptionUsername",subscriptionUsername)

    # subscription-manager password
    if not "subscriptionPassword" in config:
        subscriptionPassword = getpass.getpass('Enter subscription-manager password: ')
        save_config(config_file, "subscriptionPassword",subscriptionPassword)

    # beaker password
    if not "beakerPassword" in config:
        beakerPassword = question("string","""Specify the beaker root password,
        which can be found in user preferences on the beaker website.  This is used
        to configure keyless SSH for ansible access to the hosts.  If you are not
        using beaker, simply specify the root password of the hosts (the passwords
        should all be in common)""")
        save_config(config_file, "beakerPassword",beakerPassword)

    # Reload configurations to pull in the new settings
    config = load_config(config_file)

    # Set variables
    subscriptionUsername = config["subscriptionUsername"]
    subscriptionPassword = config["subscriptionPassword"]
    beakerPassword = config["beakerPassword"]

    # Create an empty ansible_hosts file if it doesn't exist
    create_ansiblehosts()

    # Don't run beakerReserve() if --no-beaker is set
    if args.no_beaker == True:
        print (fore.LIGHT_BLUE + style.BOLD + "\nno-beaker flag detected"
        + style.RESET)
        print "Skipping beaker reservation"
    else:
        beaker_reserve()

    # Generate Ansible prerequisites
    generate_prereqs()

    # Issue an ansible ping command
    ansibleInventory = Inventory(host_list='ansible_hosts')
    ansible_ping()

    # Subscribe hosts to the correct repos
    subscribe_hosts()

    # Build the playbook, unless --no-ansible is set
    if args.no_ansible == True:
        print (fore.LIGHT_BLUE + style.BOLD + "\nno-ansible flag detected"
        + style.RESET)
        print "Skipping automated Ansible playbook editing"
    else:
        build_playbook()

    # Run the ansible playbook
    run_playbook()

if __name__ == "__main__":
    main()
