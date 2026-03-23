workspace "Name" "Description" {

    !identifiers hierarchical

    model {
        u = person "PHA User" {
            description "A user at a public health agency within a jurisdiction"
        }
        did = softwareSystem "Difference in Docs" {
            description "Determines differences between eCRs based on configuration"
            tags "DiffInDocs"

            db = container "Database" {
                description "Configuration rules, previously seen eCR metadata, API user info, etc."
                tags "Database"
                technology "AWS DynamoDB"
            }
            backend = container "Backend" {
                description "Provides functionality via REST API"
                tags "Backend"
                technology "FastAPI, Python"
            }
            ui = container "UI" {
                description "Allows users to manage configurations"
                tags "UI"
                technology "React, Typescript"
            }
            s3 = container "Storage Account" {
                description "Stores eCR data with input and output buckets"
                tags "S3"
                technology "AWS S3"
            }
            sqs = container "Message Queue" {
                description "Holds incoming eCR data"
                tags "Queue"
                technology "AWS SQS"
            }
            lambda = container "Lambda" {
                description "Runs function to determine differences between eCRs based on configuration"
                tags "Lambda"
                technology "AWS Lambda, Python"
            }
        }
        keycloak = softwareSystem "Keycloak" {
            description "Handles user authentication and authorization"
            tags "Keycloak"
        }

        u -> did.ui "Manages configuration using" "Browser"
        did.backend -> keycloak "Manages auth using" "OAuth2"
        did.lambda -> did.s3 "Reads from and writes output to" "HTTPS"
        did.lambda -> did.db "Reads from and writes to" "HTTPS"
        did.backend -> did.db "Reads from and writes to" "HTTPS"
        did.ui -> did.backend "Makes API requests to" "HTTPS"
        did.s3 -> did.sqs "Sends eCR events to" "SNS"
        did.sqs -> did.lambda "Invokes with eCR input data" "SNS"
    }

    views {
        systemContext did "Diagram1" {
            include *
        }

        container did "Diagram2" {
            include *
        }

        styles {
            element "Element" {
                color #0773af
                stroke #0773af
                strokeWidth 7
                shape roundedbox
            }
            element "Boundary" {
                strokeWidth 5
            }
            element "Person" {
                background "#6e99b2"
                stroke "#afcadb"
                color "#ffffff"
                shape person
            }
            element "DiffInDocs" {
                background "#ffffff"
                stroke "#6499af"
                color "#6499af"
                icon "./icons/dibbs-logo.png"
            }
            element "Database" {
                background "#ed2bf7"
                stroke "#971b9e"
                color "#ffffff"
                shape cylinder
                icon "./icons/aws-dynamodb.png"
            }
            element "Backend" {
                background "#06bdaa"
                stroke "#049789"
                color "#ffffff"
                shape component
                icon "./icons/fastapi-logo.png"
            }
            element "Lambda" {
                background "#e48125"
                stroke "#cc5717"
                color "#ffffff"
                shape shell
                icon "./icons/aws-lambda.png"
            }
            element "UI" {
                background "#dbf6ff"
                stroke "#3b7082"
                color "#3b7082"
                icon "./icons/react-logo.png"
                shape webbrowser
            }
            element "S3" {
                background "#8caf31"
                stroke "#7aa116"
                color "#ffffff"
                shape bucket
                icon "./icons/aws-s3.png"
            }
            element "Queue" {
                background "#d72b6c"
                stroke "#af2359"
                color "#ffffff"
                shape pipe
                icon "./icons/aws-simple-queue-service.png"
            }
            element "Keycloak" {
                background "#737373"
                stroke "#191919"
                color "#ffffff"
                icon "./icons/keycloak-logo.png"
                shape hexagon
            }
            relationship "Relationship" {
                thickness 4
            }
        }
    }

    configuration {
        scope softwareSystem
    }
}