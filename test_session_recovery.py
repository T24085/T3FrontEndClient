import unittest
from unittest.mock import patch
from community_transport import CommunityClient,CommunityError,CommunityConnectionError

class SessionRecoveryTests(unittest.TestCase):
 def client(self):return CommunityClient('community.test',18443,'100.101.0.1',{})
 def response(self):return {'room':{'code':'ABC234','playerId':'one'},'token':'t'*32}
 def test_same_lobby_can_be_joined_again_with_local_membership(self):
  c=self.client();c._remember(self.response())
  with patch.object(c,'_request',return_value=self.response())as request:
   self.assertEqual(c.join('ABC234','One')['code'],'ABC234')
   request.assert_called_once_with('join',{'code':'ABC234','name':'One'})
 def test_create_recovers_local_session_instead_of_reporting_already_joined(self):
  c=self.client();c._remember(self.response())
  with patch.object(c,'_request',return_value={'room':self.response()['room']}):self.assertEqual(c.create('One')['code'],'ABC234')
 def test_confirmed_expired_local_membership_does_not_block_a_new_lobby(self):
  c=self.client();c._remember(self.response())
  with patch.object(c,'_request',side_effect=[CommunityError('gone','lobby_missing'),self.response()]):self.assertEqual(c.create('One')['code'],'ABC234')
 def test_network_failure_does_not_discard_a_possibly_live_membership(self):
  c=self.client();c._remember(self.response())
  with patch.object(c,'_request',side_effect=CommunityError('offline')):
   with self.assertRaises(CommunityError):c.create('One')
  self.assertEqual(c.code,'ABC234')
 def test_resume_recovers_membership_without_storing_tokens_on_disk(self):
  c=self.client()
  with patch.object(c,'_request',return_value=self.response()):self.assertEqual(c.resume()['code'],'ABC234')
  with patch.object(c,'_request',return_value={'room':None}):self.assertIsNone(c.resume())
  self.assertIsNone(c.code);self.assertIsNone(c.token)
 def test_conflicting_match_map_is_rejected(self):
  c=self.client()
  with self.assertRaisesRegex(CommunityError,'selected map'):c._validated_target({'map':'Snowblind'},'Stonehenge')
 def test_connection_failure_is_distinct_from_a_server_rejection(self):
  c=self.client()
  with patch('community_transport.PinnedHTTPSConnection')as connection:
   connection.return_value.request.side_effect=TimeoutError('lost reply')
   with self.assertRaises(CommunityConnectionError)as error:c.capabilities()
   self.assertIsInstance(error.exception.__cause__,TimeoutError)
   connection.return_value.close.assert_called_once()

if __name__=='__main__':unittest.main()
