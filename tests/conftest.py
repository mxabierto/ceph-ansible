import pytest
import os


@pytest.fixture(scope="module")
def setup(host):
    cluster_address = ""
    container_binary = ""
    osd_ids = []
    osds = []

    ansible_vars = host.ansible.get_variables()
    ansible_facts = host.ansible("setup")

    docker = ansible_vars.get("docker")
    osd_auto_discovery = ansible_vars.get("osd_auto_discovery")
    group_names = ansible_vars["group_names"]
    fsid = ansible_vars.get("fsid")

    ansible_distribution = ansible_facts["ansible_facts"]["ansible_distribution"]

    subnet = ".".join(ansible_vars["public_network"].split(".")[0:-1])
    num_mons = len(ansible_vars["groups"]["mons"])
    if osd_auto_discovery:
        num_osds = 3
    else:
        num_osds = len(ansible_vars.get("devices", []))
    if not num_osds:
        num_osds = len(ansible_vars.get("lvm_volumes", []))
    osds_per_device = ansible_vars.get("osds_per_device", 1)
    num_osds = num_osds * osds_per_device

    if ansible_distribution == "RedHat":
        public_interface = "ens6"
        cluster_interface = "ens7"
    else:
        public_interface = "eth1"
        cluster_interface = "eth2"

    # If number of devices doesn't map to number of OSDs, allow tests to define
    # that custom number, defaulting it to ``num_devices``
    num_osds = ansible_vars.get('num_osds', num_osds)
    cluster_name = ansible_vars.get("cluster", "ceph")
    conf_path = "/etc/ceph/{}.conf".format(cluster_name)
    if "osds" in group_names:
        cluster_address = host.interface(cluster_interface).addresses[0]
        cmd = host.run('sudo ls /var/lib/ceph/osd/ | sed "s/.*-//"')
        if cmd.rc == 0:
            osd_ids = cmd.stdout.rstrip("\n").split("\n")
            osds = osd_ids
            if docker and fsid == "6e008d48-1661-11e8-8546-008c3214218a":
                osds = []
                for device in ansible_vars.get("devices", []):
                    real_dev = host.run("sudo readlink -f %s" % device)
                    real_dev_split = real_dev.stdout.split("/")[-1]
                    osds.append(real_dev_split)

    address = host.interface(public_interface).addresses[0]

    if docker:
        container_binary = "docker"
    if docker and host.exists("podman") and ansible_distribution in ["Fedora", "RedHat"]:  # noqa E501
        container_binary = "podman"

    data = dict(
        cluster_name=cluster_name,
        subnet=subnet,
        osd_ids=osd_ids,
        num_mons=num_mons,
        num_osds=num_osds,
        address=address,
        osds=osds,
        conf_path=conf_path,
        cluster_address=cluster_address,
        container_binary=container_binary)

    return data

@pytest.fixture()
def node(host, request):
    """
    This fixture represents a single node in the ceph cluster. Using the
    host.ansible fixture provided by testinfra it can access all the ansible
    variables provided to it by the specific test scenario being ran.

    You must include this fixture on any tests that operate on specific type
    of node because it contains the logic to manage which tests a node
    should run.
    """
    ansible_vars = host.ansible.get_variables()
    # tox will pass in this environment variable. we need to do it this way
    # because testinfra does not collect and provide ansible config passed in
    # from using --extra-vars
    ceph_stable_release = os.environ.get("CEPH_STABLE_RELEASE", "luminous")
    rolling_update = os.environ.get("ROLLING_UPDATE", "False")
    group_names = ansible_vars["group_names"]
    docker = ansible_vars.get("docker")
    osd_scenario = ansible_vars.get("osd_scenario")
    radosgw_num_instances = ansible_vars.get("radosgw_num_instances", 1)
    lvm_scenario = osd_scenario in ['lvm', 'lvm-batch']
    ceph_release_num = {
        'jewel': 10,
        'kraken': 11,
        'luminous': 12,
        'mimic': 13,
        'dev': 99
    }

    # capture the initial/default state
    test_is_applicable = False
    for marker in request.node.iter_markers():
        if marker.name in group_names or marker.name == 'all':
            test_is_applicable = True
            break
    # Check if any markers on the test method exist in the nodes group_names.
    # If they do not, this test is not valid for the node being tested.
    if not test_is_applicable:
        reason = "%s: Not a valid test for node type: %s" % (
            request.function, group_names)
        pytest.skip(reason)

    if request.node.get_closest_marker("no_lvm_scenario") and lvm_scenario:
        pytest.skip("Not a valid test for lvm scenarios")

    if not lvm_scenario and request.node.get_closest_marker("lvm_scenario"):
        pytest.skip("Not a valid test for non-lvm scenarios")

    if request.node.get_closest_marker("no_docker") and docker:
        pytest.skip(
            "Not a valid test for containerized deployments or atomic hosts")

    if request.node.get_closest_marker("docker") and not docker:
        pytest.skip(
            "Not a valid test for non-containerized deployments or atomic hosts")  # noqa E501

    journal_collocation_test = ansible_vars.get("osd_scenario") == "collocated"
    if request.node.get_closest_marker("journal_collocation") and not journal_collocation_test:  # noqa E501
        pytest.skip("Scenario is not using journal collocation")



    data = dict(
        vars=ansible_vars,
        docker=docker,
        ceph_stable_release=ceph_stable_release,
        ceph_release_num=ceph_release_num,
        rolling_update=rolling_update,
        radosgw_num_instances=radosgw_num_instances,
    )
    return data


def pytest_collection_modifyitems(session, config, items):
    for item in items:
        test_path = item.location[0]
        if "mon" in test_path:
            item.add_marker(pytest.mark.mons)
        elif "osd" in test_path:
            item.add_marker(pytest.mark.osds)
        elif "mds" in test_path:
            item.add_marker(pytest.mark.mdss)
        elif "mgr" in test_path:
            item.add_marker(pytest.mark.mgrs)
        elif "rbd-mirror" in test_path:
            item.add_marker(pytest.mark.rbdmirrors)
        elif "rgw" in test_path:
            item.add_marker(pytest.mark.rgws)
        elif "nfs" in test_path:
            item.add_marker(pytest.mark.nfss)
        elif "iscsi" in test_path:
            item.add_marker(pytest.mark.iscsigws)
        else:
            item.add_marker(pytest.mark.all)

        if "journal_collocation" in test_path:
            item.add_marker(pytest.mark.journal_collocation)
