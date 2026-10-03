"""Compose configured selector clicks with the existing physical warm journey."""
import json
import os
from pathlib import Path
import pickle
import shlex

from record_installed_tui import InputWarmJourney, marker_command, native_click_command, main


class SelectorWarmJourney(InputWarmJourney):
    review_artifacts = (*InputWarmJourney.review_artifacts, 'selector-review.json')

    @classmethod
    def opening_commands(cls, args):
        model = os.environ['TOAD_TEST_SELECTOR_MODEL']
        marker = marker_command()
        return (cls.ready_command(args, 'selector-ready', cls.history_thread(args)),
                native_click_command('phase-selector-ready-state.pickle', target='widget', name='AgentInfo'),
                f'sleep {args.navigation_settle_seconds:g}', marker + 'selector-picker',
                'type --clearmodifiers --delay 20 ' + shlex.quote(model),
                f'sleep {args.navigation_settle_seconds:g}', marker + 'selector-filtered',
                'key Return', f'sleep {args.navigation_settle_seconds:g}', marker + 'selector-acknowledged',
                'key Escape', f'sleep {args.navigation_settle_seconds:g}', marker + 'selector-closed',
                *super().opening_commands(args))

    @classmethod
    def review(cls, output, receipt):
        result = super().review(output, receipt)
        def configuration(label):
            snapshot = pickle.loads((output / f'phase-{label}-state.pickle').read_bytes())
            mode = snapshot['metadata']['current_mode']
            view, = (view for view in snapshot['views'] if view['mode'] == mode)
            return view['agent_configuration']
        before, after, returned = (configuration(label) for label in ('selector-ready', 'selector-closed', 'a-return'))
        checks = {
            'same_original_agent_after_selector_and_return': before['agent_object_id'] == after['agent_object_id'] == returned['agent_object_id'],
            'same_original_session_after_selector_and_return': before['session_id'] == after['session_id'] == returned['session_id'],
            'acknowledged_configured_model_preserved': before['model'] == after['model'] == returned['model'] == os.environ['TOAD_TEST_SELECTOR_MODEL'],
            'configured_thinking_preserved': before['thinking'] == after['thinking'] == returned['thinking'],
            'accepted_label_preserved': before['rendered_label'] == after['rendered_label'] == returned['rendered_label'],
        }
        result['selectors'] = {'checks': checks, 'before': before, 'after': after, 'returned': returned,
                               'scope': 'Actual click/filter/Enter/cancel on same configured model; no provider prompt'}
        (output / 'selector-review.json').write_text(json.dumps(result['selectors'], indent=2) + '\n')
        return result

    @classmethod
    def validate_review(cls, result):
        super().validate_review(result)
        failed = [name for name, passed in result['selectors']['checks'].items() if not passed]
        if failed:
            raise RuntimeError('Configured selector warm journey failed: ' + ', '.join(failed))


if __name__ == '__main__':
    main()
