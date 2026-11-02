import unittest
from probe import isolated_environment


class IsolationTest(unittest.TestCase):
    def test_sensitive_variables_do_not_reach_dependencies(self):
        env={'PATH':'/bin','HOME':'/tmp','GDRIVE_REFRESH_TOKEN':'synthetic','GH_TOKEN':'synthetic',
             'ARK_API_KEY':'synthetic','RANDOM_SECRET':'synthetic'}
        self.assertEqual(isolated_environment(env),{'PATH':'/bin','HOME':'/tmp'})


if __name__=='__main__':unittest.main()
