set working-directory := "../docs"

alias h := _default
alias help := _default

# List commands for structurizr
@_default:
    just --list arch

alias start := view
alias open := view

[doc('Sets up the Structurizr instance locally on port 7268.')]
view:
    @echo "*******************\n\n🌐 View Structurizr in your browser at http://localhost:7268\n\n*******************\n"
    docker compose -f compose.structurizr.yml up structurizr

[doc('Exports diagrams in puml format (C4 PlantUML) into a `diagrams/` directory.')]
render-c4plantuml:
    docker compose -f compose.structurizr.yml run --rm structurizr \
        export \
        -workspace workspace.json \
        -format plantuml/c4plantuml \
        -output diagrams

[doc('Exports diagrams in mmd format (Mermaid) into a `diagrams/` directory. Useful for quickly including diagrams into GitHub-rendered Markdown.')]
render-mermaid:
    docker compose -f compose.structurizr.yml run --rm structurizr \
        export \
        -workspace workspace.json \
        -format mermaid \
        -output diagrams
