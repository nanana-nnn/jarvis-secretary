import asyncio
from pathlib import Path
from types import SimpleNamespace

from server.approval import ApprovalStore
from server.session import Session
from server.agent import CodexAgent


def test_timeout_delivers_completion_after_cleanup(tmp_path, monkeypatch):
    async def check():
        import server.approval as module
        monkeypatch.setattr(module, 'APPROVAL_TIMEOUT_S', 0)
        delivered = []
        class Socket:
            async def send_json(self, event):
                await asyncio.sleep(0)  # Real network sends can suspend.
                delivered.append(event)
        proposal = tmp_path / 'work' / 'vault'
        proposal.mkdir(parents=True)
        store = ApprovalStore(tmp_path, str(tmp_path / 'audit.jsonl'))
        store.hold('job', dict(proposal=proposal, intent='CAPTURE', text='save', changed_files=[]), Socket())
        timer = store.pending['job']['timer']
        await asyncio.gather(timer, return_exceptions=True)
        assert not proposal.exists()
        assert delivered and delivered[0]['type'] == 'agent.completed'
    asyncio.run(check())


def test_disconnect_stops_agent_before_session_returns(tmp_path):
    async def check():
        started = asyncio.Event()
        stopped = asyncio.Event()
        class Agent:
            async def run(self, *args, **kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
        class Socket:
            async def send_json(self, event): pass
            async def receive(self):
                await started.wait()
                return {'type': 'websocket.disconnect'}
        session = Session(Socket(), SimpleNamespace(vault_path=tmp_path), Agent(), None, None)
        session.job = asyncio.create_task(session._run_agent('hello', SimpleNamespace(intent='ASK', matched='', long=False, mode='read_only')))
        await session.run()
        assert stopped.is_set()
        assert session.job.done()
    asyncio.run(check())


def test_proposal_does_not_treat_concurrent_user_edits_as_agent_changes(tmp_path):
    async def check():
        vault = tmp_path / 'vault'
        vault.mkdir()
        (vault / 'note.md').write_text('before\n')
        (vault / 'other.md').write_text('untouched\n')
        class Terminal:
            async def run(self, command, cwd, prompt_file, timeout):
                (vault / 'note.md').write_text('user edit\n')
                (vault / 'other.md').write_text('another user edit\n')
                (cwd / 'note.md').write_text('agent edit\n')
                (prompt_file.parent / 'answer.json').write_text('{"summary":"done","spoken_reply":"done","sources":[]}')
                return 0
        agent = CodexAgent(vault, visible=False)
        agent.terminal = Terminal()
        result = await agent.run('save', 'propose_write')
        try:
            assert result.changed_files == ['note.md']
            assert result.original_contents == {'note.md': b'before\n'}
        finally:
            import shutil
            if result.proposed_root:
                shutil.rmtree(result.proposed_root.parent)
    asyncio.run(check())
