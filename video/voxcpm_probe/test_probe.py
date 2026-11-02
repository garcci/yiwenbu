import unittest
from probe import isolated_environment


class IsolationTest(unittest.TestCase):
    def test_sensitive_variables_do_not_reach_dependencies(self):
        env={'PATH':'/bin','HOME':'/tmp','GDRIVE_REFRESH_TOKEN':'synthetic','GH_TOKEN':'synthetic',
             'ARK_API_KEY':'synthetic','RANDOM_SECRET':'synthetic'}
        result=isolated_environment(env)
        self.assertEqual(result['PATH'],'/bin')
        self.assertNotEqual(result['HOME'],'/tmp')
        self.assertFalse(any(key in result for key in ('GDRIVE_REFRESH_TOKEN','GH_TOKEN','ARK_API_KEY','RANDOM_SECRET')))


if __name__=='__main__':unittest.main()
