"""Affected installed family sanity only; no package/source overlay or provider."""
import asyncio
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import sys
import subprocess

def main():
    prefix = Path(sys.prefix).resolve()
    root = Path('/home/ts/wt/toad-transcript-source-lifetime-main-20261002')
    out = root / '.artifacts/installed-publication-family'
    sources = {}
    for name, distribution in (('toad', 'batrachian-toad'), ('textual', 'textual'),
                               ('agent_comms', 'agent-comms')):
        module = __import__(name)
        location = Path(module.__file__).resolve()
        assert location.is_relative_to(prefix), location
        sources[name] = {
            'module': str(location),
            'direct_url': json.loads(metadata.distribution(distribution).read_text('direct_url.json')),
        }
    
    from toad import transcript_publication
    receiver = Path('/home/ts/wt/toad-critical-compaction501-release-20261001')
    receiver_head = 'c97255e80fd8a32dff312a44c24cddc01b12d29e'
    expected = subprocess.check_output(['git', '-C', str(receiver), 'show',
                                        receiver_head + ':src/toad/transcript_publication.py'])
    installed = Path(transcript_publication.__file__).read_bytes()
    assert installed == expected, 'Installed publication differs from reviewed final source'
    assert sources['toad']['direct_url']['vcs_info']['commit_id'] == receiver_head
    assert sources['textual']['direct_url']['vcs_info']['commit_id'] == 'e36d7ee4b8b1945ebf90fcb840753a68fe2ae16d'
    assert sources['agent_comms']['direct_url']['vcs_info']['commit_id'] == '0f63cfb0e8bbf77b32dc803b81481428fa38cd99'
    
    # This path contains only test-owned helpers. Product modules were imported
    # above from this immutable prefix and no repository src is on sys.path.
    sys.path.insert(0, str(root / 'tests'))
    spec = importlib.util.spec_from_file_location('publication_family', root / 'tests/guards/test_transcript_publication.py')
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    asyncio.run(driver.declaration_case())
    receipt = {
        'state': 'PASS_AFFECTED_INSTALLED_APP_AND_CERTIFIED_READ_FAMILY',
        'prefix': str(prefix), 'sources': sources,
        'publication_sha256': hashlib.sha256(installed).hexdigest(),
        'provider_calls': 0, 'original_input_replayed': False,
        'product_source_overlay': False, 'public_mutation': False,
        'scope': 'original UI pump/application epoch, held certified read decline, fresh read once, cancel/close',
        'physical_ABA': 'separate sole Heisenberg gate; not covered by this App sanity',
    }
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
