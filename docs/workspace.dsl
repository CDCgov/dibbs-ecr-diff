workspace "Name" "Description" {

    !identifiers hierarchical

    model {
        aims = softwareSystem "AIMS Platform" {
            description "Handles incoming eCRs and decides whether to send to PHAs. Includes eCR Refiner."
            tags "AIMS"
        }
        did = softwareSystem "Difference in Docs" {
            description "Determines differences between eCRs based on configuration"
            tags "DiffInDocs"

            db = container "Database" {
                description "Stores previously seen eCR metadata"
                tags "Database"
                technology "AWS DynamoDB"
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
                description "Runs function to determine differences between eCR versions"
                tags "Lambda"
                technology "AWS Lambda, Python"
            }
        }
        
        aims -> did.s3 "Sends eCR input to"
        did.s3 -> did.sqs "Publishes notification events to" "SNS"
        did.sqs -> did.lambda "Invokes with event as input" "SNS"
        did.lambda -> did.db "Reads from and writes to" "HTTPS"
        did.lambda -> did.s3 "Reads from and writes to" "HTTPS"
        did.s3 -> aims "Sends diff output to"
    }

    views {
        systemContext did "Diagram1" {
            include *
            title "System Context View: Difference in Docs, Iteration 1 DRAFT"
        }
        container did "Diagram2" {
            include *
            title "Container View: Difference in Docs, Iteration 1 DRAFT"
        }

        dynamic did "Sequence1" {
            title "Sequence Diagram: Difference in Docs, Iteration 1 DRAFT"

            aims -> did.s3 "Adds eCR to an input bucket on"
            did.s3 -> did.sqs "Publishes event with eCR metadata to"
            did.sqs -> did.lambda "Triggers with eCR metadata as input"
            did.lambda -> did.db "Persists eCR metadata with bucket URL to"
            did.lambda -> did.db "Queries for previous eCR version with matching Set ID"
            did.db -> did.lambda "Returns previous eCR version metadata with bucket URL if it exists"
            did.lambda -> did.s3 "Fetches eCR files of current and previous version using saved bucket URLs"
            did.s3 -> did.lambda "Returns eCR files of current and previous version to compare"
            did.lambda -> did.s3 "Adds diff output to"
            did.s3 -> aims "Triggers remaining AIMS processing"
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
            element "AIMS" {
                background "#ffffff"
                stroke "#009ca7"
                color "#009ca7"
                icon "./icons/aphl-aims.png"
            }
            element "Database" {
                background "#ed2bf7"
                stroke "#971b9e"
                color "#ffffff"
                shape cylinder
                icon "./icons/aws-dynamodb.png"
            }
            element "Lambda" {
                background "#e48125"
                stroke "#cc5717"
                color "#ffffff"
                shape shell
                icon "./icons/aws-lambda.png"
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
            element "UI" {
                background "#dbf6ff"
                stroke "#3b7082"
                color "#3b7082"
                icon "./icons/react-logo.png"
                shape webbrowser
            }
            element "Backend" {
                background "#06bdaa"
                stroke "#049789"
                color "#ffffff"
                shape component
                icon "./icons/fastapi-logo.png"
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