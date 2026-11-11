# Keyless demo. Run from the repository root: vhs tools/demo.tape
# Set DEMO_BIN to the bin folder of a virtualenv with the requirements installed, for example DEMO_BIN=.venv/bin vhs tools/demo.tape
Output media/demo.gif
Set Shell "bash"
Set FontFamily "Menlo"
Set FontSize 21
Set Width 1200
Set Height 460
Set Padding 24
Set Framerate 12
Set TypingSpeed 30ms
Set Theme { "name": "graphite", "black": "#0e1117", "red": "#b5654a", "green": "#4f9a6f", "yellow": "#8b949e", "blue": "#79a890", "magenta": "#8b949e", "cyan": "#79a890", "white": "#e6e9ee", "brightBlack": "#2c333d", "brightRed": "#b5654a", "brightGreen": "#4f9a6f", "brightYellow": "#8b949e", "brightBlue": "#79a890", "brightMagenta": "#8b949e", "brightCyan": "#79a890", "brightWhite": "#e6e9ee", "background": "#0e1117", "foreground": "#e6e9ee", "selection": "#2c333d", "cursor": "#79a890" }

Hide
Type "export PATH=$DEMO_BIN:$PATH T=$(mktemp -d /tmp/demo.XXXXXX) PS1='\[\e[38;2;139;148;158m\]$ \[\e[0m\]'"
Enter
Type "export RESEARCH_RUNS_DIR=$T/runs; python3 -c 'import reportlab' || exit 1; clear"
Enter
Sleep 400ms
Show

Type "python3 samples/fake_run.py $T/report.pdf"
Enter
Sleep 3s
Type "ls -1 $T"
Enter
Sleep 2.5s

Hide
Type "clear"
Enter
Sleep 400ms
Show
Type "python3 tools/facts.py"
Enter
Sleep 4.5s

Hide
Type "clear"
Enter
Sleep 400ms
Show
Type "sed -n 5,16p evals/results/latest.md | cut -d'|' -f2-5"
Enter
Sleep 6s
