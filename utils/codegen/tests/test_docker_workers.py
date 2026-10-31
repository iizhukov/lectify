import pytest
from templates import env


def workers_class():
    namespace = {}
    exec(env.get_template('services/docker_workers.py.j2').render(),namespace)
    return namespace['DockerWorkers']


def test_placement_is_replica_independent_and_preserves_existing_assignments():
    Workers = workers_class()
    inventory = {'daemon-a':object(),'daemon-b':object(),'daemon-c':object()}
    first, second = Workers(inventory), Workers(dict(reversed(tuple(inventory.items()))))
    expanded = Workers({**inventory,'daemon-d':object()})
    winners = set()
    for node in range(200):
        args = ('execution',str(node),'plugin')
        winner, sandbox = first.choose(*args)
        assert second.choose(*args) == (winner,sandbox)
        new_winner, _ = expanded.choose(*args)
        assert new_winner in (winner,'daemon-d')
        assert expanded.choose(*args,daemon_id=winner) == (winner,sandbox)
        winners.add(winner)
    assert winners == set(inventory)
    inventory.clear()
    assert first.choose('execution','node','plugin')[0] in winners
    with pytest.raises(RuntimeError,match='unavailable'):
        first.choose('execution','node','plugin',daemon_id='removed-worker')
