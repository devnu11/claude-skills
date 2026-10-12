"""Verb data for the naming rules. Data only: every value here is a table."""

HUMAN_VERBS = frozenset(
    """
    get fetch find search load set update reset clear create build initialize init start
    stop open close delete remove destroy is has can should validate check parse format
    calculate compute change edit add append save store disable hide split separate merge
    join make generate copy clone begin retrieve read
    """.split()
)

# https://learn.microsoft.com/powershell/scripting/developer/cmdlet/approved-verbs-for-windows-powershell-commands
POWERSHELL_VERBS = frozenset(
    """
    add clear close copy enter exit find format get hide join lock move new open optimize
    pop push redo remove rename reset resize search select set show skip split step switch
    undo unlock watch
    connect disconnect read receive send write
    backup checkpoint compare compress convert dismount edit expand export group import
    initialize limit merge mount out publish restore save sync unpublish update
    debug measure ping repair resolve test trace
    approve assert build complete confirm deny deploy disable enable install invoke register
    request restart resume start stop submit suspend uninstall unregister wait
    block grant protect revoke unblock unprotect
    use
    foreach sort tee where
    """.split()
)

PROGRAMMING_VERBS = frozenset(
    """
    accept apply ask attach bind call cancel classify collect commit contain count cover
    decide decode grade
    describe detach dispatch do drain drop dump emit encode ensure escape expect extend
    extract fail filter flush fork gather guard handle inject insert iterate keep kill
    launch lay list log look map mark match mutate note notify parse pick plan poll prepare print
    probe process pull put raise rank record reduce refresh reject relay release render
    replace report require retry return route run scan schedule screen serialize settle
    signal sleep spawn strip subscribe sum summarize take tell throw tick track transform
    translate trim try unwrap visit walk wrap yield
    address advance answer attempt audit await bounce capture carry charge claim continue
    deliver detect enforce escalate evaluate execute finish fit forward guide hand hold
    include interrupt land leave normalize offer onboard override own pass prioritize pump
    quarantine queue reach reconnect recover reorder repeat revert review rework roll seed
    serve stall stub suggest summarize tail wake
    """.split()
)

# Prefixes that read as conversions or handlers in Python: to_dict, as_tuple, on_click.
CONVENTION_PREFIXES = frozenset({"to", "as", "on"})

# Words that ask a question. A boolean property may start with one (``is_empty``).
PREDICATES = frozenset({"is", "has", "can", "should", "was", "will", "needs"})

# PowerShell's "synonyms to avoid", minus words that are approved verbs themselves
# and minus ``create``, which names factories here.
SYNONYMS = {
    "append": "add",
    "attach": "add",
    "concatenate": "add",
    "insert": "add",
    "flush": "clear",
    "erase": "clear",
    "unset": "clear",
    "nullify": "clear",
    "duplicate": "copy",
    "clone": "copy",
    "replicate": "copy",
    "obtain": "get",
    "acquire": "get",
    "examine": "get",
    "fetch": "get",
    "retrieve": "get",
    "combine": "join",
    "unite": "join",
    "associate": "join",
    "restrict": "lock",
    "secure": "lock",
    "transfer": "move",
    "migrate": "move",
    "generate": "new",
    "make": "new",
    "allocate": "new",
    "delete": "remove",
    "eliminate": "remove",
    "destroy": "remove",
    "dispose": "remove",
    "discard": "remove",
    "cut": "remove",
    "change": "edit, convert or rename",
    "modify": "edit",
    "locate": "search or select",
    "assign": "set",
    "configure": "set",
    "display": "show",
    "produce": "show",
    "bypass": "skip",
    "jump": "skip",
    "separate": "split",
    "unrestrict": "unlock",
    "login": "connect",
    "logoff": "disconnect",
    "peek": "receive",
    "broadcast": "send",
    "mail": "send",
    "print": "write",
    "diff": "compare",
    "compact": "compress",
    "unmount": "dismount",
    "unlink": "dismount",
    "explode": "expand",
    "uncompress": "expand",
    "extract": "export",
    "init": "initialize",
    "setup": "initialize",
    "renew": "initialize",
    "rebuild": "initialize",
    "reinitialize": "initialize",
    "fix": "repair",
    "refresh": "update",
    "recalculate": "update",
    "reindex": "update",
    "diagnose": "debug",
    "calculate": "measure",
    "determine": "measure",
    "analyze": "measure",
    "verify": "test",
    "track": "trace",
    "follow": "trace",
    "inspect": "trace",
    "certify": "assert",
    "acknowledge": "confirm",
    "validate": "confirm",
    "refuse": "deny",
    "reject": "deny",
    "halt": "disable",
    "begin": "start",
    "launch": "start",
    "initiate": "start",
    "boot": "start",
    "recycle": "restart",
    "end": "stop",
    "kill": "stop",
    "terminate": "stop",
    "cancel": "stop",
    "post": "submit",
    "pause": "suspend",
    "sleep": "wait",
    "prevent": "block",
    "allow": "grant",
    "encrypt": "protect",
    "seal": "protect",
    "decrypt": "unprotect",
    "unseal": "unprotect",
}

VERBS = HUMAN_VERBS | POWERSHELL_VERBS | PROGRAMMING_VERBS | CONVENTION_PREFIXES | set(SYNONYMS)

# Verbs whose call on ``self`` (or on one of its attributes) changes the object.
MUTATING_VERBS = frozenset(
    """
    set add append extend insert remove delete discard pop clear update reset write save
    store push put emit record mark register unregister move rename replace drop
    """.split()
)
