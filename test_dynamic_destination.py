import unittest
from dynamic_destination import destination

class DestinationTest(unittest.TestCase):
    def setUp(self):
        self.policy = {'server_address':'100.80.168.96', 'first_port':18000, 'last_port':18999}

    def test_configured_server_and_test_scope(self):
        self.assertEqual(destination('100.80.168.96:18818', self.policy), '100.80.168.96:18818')
        self.assertEqual(destination('127.0.0.1:18787', self.policy, test_source='127.0.0.2'), '127.0.0.1:18787')
        self.assertEqual(destination('127.0.0.1:18787', self.policy, test_source='127.0.0.4'), '127.0.0.1:18787')
        for address, source in [('127.0.0.1:18787', None), ('8.8.8.8:18818', None),
                                ('100.80.168.96:7787', None), ('100.80.168.96:18818', '127.0.0.2'),
                                ('127.0.0.1:18787', '127.0.0.5'), ('100.80.168.96:18x', None)]:
            with self.subTest(address=address,source=source), self.assertRaises(ValueError):
                destination(address, self.policy, test_source=source)

    def test_policy_rejects_invalid_servers_and_ports(self):
        for policy in ({'server_address':'8.8.8.8','first_port':18000,'last_port':18999},
                       {'server_address':'100.80.168.96','first_port':True,'last_port':18999},
                       {'server_address':'100.80.168.96','first_port':19000,'last_port':18999}):
            with self.assertRaises(ValueError):
                destination('100.80.168.96:18818', policy)

if __name__ == '__main__':
    unittest.main(verbosity=2)
