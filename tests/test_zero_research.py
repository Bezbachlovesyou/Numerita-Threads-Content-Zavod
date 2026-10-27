import json,os,unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from zavod.zero_research import excerpt, data, ADMIN_REPORT,send_admin_report
from zavod.knowledge import KnowledgeBase

class ZeroTests(unittest.IsolatedAsyncioTestCase):
 async def test_trigger_and_no_extra_context(self):
  for s in ['0','10','20','30','330','о нуле','санкхья','вивека','духовное и материальное']:
   self.assertIsNotNone(excerpt(s),s)
  self.assertIsNone(excerpt('добрый вечер, спасибо'))
 async def test_no_planet_does_not_erase_symbolism_and_conflict_corrected(self):
  context=json.loads(await KnowledgeBase('').excerpt('330 и ноль'))
  text=context['zero_and_discernment']['rule']
  self.assertIn('ОСЛАБЛЯЕТСЯ',text)
  self.assertIn('сначала спросить контекст',text)
  self.assertIn('нет отдельной планеты',text)
  self.assertEqual(len(data()['schools']),2)
 def test_report_fits(self):
  self.assertLess(len(ADMIN_REPORT),4096)
 async def test_admin_receipt_only_after_success(self):
  db=AsyncMock();db.kv_get.return_value=None;db.claim_slot.return_value=True
  bot=AsyncMock();bot.send_message.return_value=SimpleNamespace(message_id=123)
  with patch.dict(os.environ,{'RAILWAY_PROJECT_ID':'aae9ee4d-e392-46a9-892a-f656adc80955'}):
   await send_admin_report(bot,SimpleNamespace(admin_ids={42}),db)
  receipt=json.loads(db.kv_set.call_args.args[1]);self.assertEqual(receipt['message_id'],123)
  db.kv_get.return_value='already sent'
  with patch.dict(os.environ,{'RAILWAY_PROJECT_ID':'aae9ee4d-e392-46a9-892a-f656adc80955'}):
   await send_admin_report(bot,SimpleNamespace(admin_ids={42}),db)
  self.assertEqual(bot.send_message.await_count,1)
 async def test_failed_send_has_no_receipt(self):
  db=AsyncMock();db.kv_get.return_value=None;db.claim_slot.return_value=True
  bot=AsyncMock();bot.send_message.side_effect=RuntimeError('timeout')
  with patch.dict(os.environ,{'RAILWAY_PROJECT_ID':'aae9ee4d-e392-46a9-892a-f656adc80955'}):
   with self.assertRaises(RuntimeError):await send_admin_report(bot,SimpleNamespace(admin_ids={42}),db)
  db.kv_set.assert_not_called()
