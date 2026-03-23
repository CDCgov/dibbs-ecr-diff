set working-directory := "../docs"

alias h := _default
alias helper := _default

# List commands for structurizr
@_default:
    just --list arch

alias start := view
alias open := view

[doc('Sets up the Structurizr instance locally on port 7268.')]
view:
    @echo "*******************\n\n🌐 View Structurizr in your browser at http://localhost:7268\n\n*******************\n"
    docker run \
        -it \
        --rm \
        -p 7268:8080 \
        -v ./:/usr/local/structurizr \
        structurizr/structurizr \
        local
    