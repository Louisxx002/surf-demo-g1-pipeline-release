PYTHONPATH=$(echo "$PYTHONPATH" | tr ':' '\n' | grep -v '/opt/ros' | tr '\n' ':') python -m pytest "$@"
