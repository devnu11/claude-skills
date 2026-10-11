from .test_boundary_runner import env, repo, origin, commit, Edge, git  # noqa
from agile_team import boundary as bd
from agile_team.gates import StoryState, StoryStatus

def test_dbg(env, origin):
    r = env.rt.config.repo
    env.rt.state.upstream.push = bd.Permission.YES
    commit(r, "one.txt")
    env.open(Edge.END)
    env.drive()
    env.rt.state.sprint = 2
    env.rt.state.stories["s2"] = StoryState("s2", "Two", "done", status=StoryStatus.DONE, sprint=2)
    commit(r, "two.txt")
    env.open(Edge.END)
    env.drive()
    print("STACK", [(e.sprint, e.start[:7], e.end[:7], e.head[:7]) for e in env.rt.state.upstream.stack])
    print("EV", [(e.data["sprint"], e.data["stage"], e.data["outcome"], e.data.get("note"), e.data.get("reason", "")[:80]) for e in env.events()])
    assert 0
