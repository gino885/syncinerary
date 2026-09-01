import Foundation

@main
enum APIContractTests {
    static func main() throws {
        try encodeSeveralTypedCities()
        try encodeTripCreateRequest()
        try decodeTripCreatedResponse()
        try decodeGatherResponse()
        try encodeAttachmentLinkRequest()
        try decodeSourceAttachmentResponse()
        try decodeCandidateCard()
        try decodeCandidatePhoto()
        try decodeLodgingOptions()
        try encodeLodgingSelection()
        try encodeVoteRequest()
        try encodeLikeWithNoteRequest()
        try decodeVoteResponse()
        try encodeShortlistEditRequest()
        try decodeShortlistState()
        try encodePlanRequest()
        try decodePlanResponse()
        try buildItineraryViewerQuery()
        try decodeItineraryResponse()
        try encodeReplanDecision()
        try buildReplanWebSocketURL()
        try decodeReplanProposal()
        print("iOS API contract tests passed")
    }

    /// Cities are typed, so the request carries a list and must not
    /// reintroduce a single chosen destination.
    private static func encodeSeveralTypedCities() throws {
        let request = TripCreateRequest(
            cities: ["Sapporo", "Otaru"],
            country: "Japan",
            startDate: "2026-09-25",
            endDate: "2026-09-29",
            creatorName: "Gino",
            creatorHomeCity: nil,
            creatorInterests: [],
            creatorDietaryExcludes: []
        )
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
        guard let payload = object as? [String: Any] else {
            throw failure("Trip request must encode as a JSON object")
        }

        try require(
            payload["cities"] as? [String] == ["Sapporo", "Otaru"],
            "A trip must be able to search more than one typed city"
        )
        try require(
            payload["country"] as? String == "Japan",
            "A trip must name the one country its cities are in"
        )
        try require(
            payload["destination"] == nil,
            "The client must not send a destination: the backend derives it"
        )
    }

    private static func encodeTripCreateRequest() throws {
        let request = TripCreateRequest(
            cities: ["Sapporo"],
            country: "Japan",
            startDate: "2026-09-25",
            endDate: "2026-09-29",
            creatorName: "Gino",
            creatorHomeCity: nil,
            creatorInterests: ["coffee", "architecture"],
            creatorDietaryExcludes: ["seafood"]
        )
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
        guard let payload = object as? [String: Any] else {
            throw failure("Trip request must encode as a JSON object")
        }

        try require(payload["start_date"] as? String == "2026-09-25", "Trip request must encode start_date")
        try require(payload["creator_name"] as? String == "Gino", "Trip request must encode creator_name")
        try require(payload["cities"] as? [String] == ["Sapporo"], "Trip request must encode the typed cities")
        try require(payload["creator_interests"] as? [String] == ["coffee", "architecture"], "Trip request must encode interests")
        try require(payload["creator_dietary_excludes"] as? [String] == ["seafood"], "Trip request must encode dietary exclusions")
    }

    private static func decodeTripCreatedResponse() throws {
        let data = Data(
            #"""
            {
                "trip": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "destination": "Sapporo, Otaru",
                    "cities": ["Sapporo", "Otaru"],
                    "country": "Japan",
                    "timezone": "Asia/Tokyo",
                    "start_date": "2026-09-25",
                    "end_date": "2026-09-29",
                    "days": 5,
                    "status": "planning"
                },
                "traveler_id": "22222222-2222-2222-2222-222222222222"
            }
            """#.utf8
        )

        let response = try JSONDecoder().decode(TripCreatedResponse.self, from: data)
        try require(
            response.travelerID.uuidString == "22222222-2222-2222-2222-222222222222",
            "POST /trips must decode traveler_id"
        )
        try require(response.trip.startDate == "2026-09-25", "Trip dates must decode")
        try require(
            response.trip.cities == ["Sapporo", "Otaru"],
            "A trip must decode every city it is searching"
        )
        try require(
            response.trip.timezone == "Asia/Tokyo",
            "A trip must decode the destination's own timezone"
        )
    }

    private static func decodeGatherResponse() throws {
        let response = try JSONDecoder().decode(
            GatherResponse.self,
            from: Data(#"{"deck_size":35}"#.utf8)
        )
        try require(response.deckSize == 35, "Gather response must decode deck_size")
    }

    private static func encodeAttachmentLinkRequest() throws {
        let request = AttachmentLinkRequest(
            travelerID: try uuid("22222222-2222-2222-2222-222222222222"),
            url: "https://www.instagram.com/reel/Da2UDmNtLvp/",
            placeName: "Otaru Canal"
        )
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
        guard let payload = object as? [String: Any] else {
            throw failure("Attachment request must encode as a JSON object")
        }

        try require(
            payload["traveler_id"] as? String == "22222222-2222-2222-2222-222222222222",
            "Attachment request must encode traveler_id"
        )
        try require(
            payload["place_name"] as? String == "Otaru Canal",
            "Attachment request must encode an optional place_name"
        )
    }

    private static func decodeSourceAttachmentResponse() throws {
        let data = Data(
            #"{"id":"77777777-7777-7777-7777-777777777777","platform":"instagram","input_type":"link","status":"ready","original_url":"https://www.instagram.com/reel/Da2UDmNtLvp/","canonical_url":"https://www.instagram.com/reel/Da2UDmNtLvp/","has_screenshot":false,"submitted_place_name":"Otaru Canal","candidate_id":"33333333-3333-3333-3333-333333333333","contributor":{"id":"22222222-2222-2222-2222-222222222222","name":"Gino"}}"#.utf8
        )

        let response = try JSONDecoder().decode(SourceAttachmentResponse.self, from: data)
        try require(response.status == "ready", "Attachment status must decode")
        try require(response.submittedPlaceName == "Otaru Canal", "Place name must decode")
        try require(response.contributor.name == "Gino", "Contributor must decode")
    }

    private static func decodeCandidateCard() throws {
        let data = Data(
            #"""
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "type": "attraction",
                "name_canonical": "Odori Park",
                "name_original_lang": null,
                "lat": 43.0605,
                "lng": 141.3544,
                "area": "Sapporo",
                "address": null,
                "category": "park",
                "price_tier": 0,
                "duration_estimate_min": 60,
                "dietary_tags": [],
                "dietary_notice": null,
                "source_badges": [{
                    "kind": "attached_by_you",
                    "label": "Attached by you",
                    "contributor_name": "Gino"
                }],
                "delegate_badge": {
                    "type": "confirm",
                    "text": "Matches your love of parks",
                    "reasoning": "You listed parks as an interest."
                }
            }
            """#.utf8
        )

        let response = try JSONDecoder().decode(CandidateCard.self, from: data)
        try require(response.nameCanonical == "Odori Park", "Candidate names must decode")
        try require(response.durationEstimateMin == 60, "Candidate durations must decode")
        try require(response.sourceBadges[0].label == "Attached by you", "Source badges must decode")
        try require(response.dietaryNotice == nil, "A non-food card has no dietary notice")
        try require(response.delegateBadge?.type == "confirm", "Personal delegate badges must decode")
    }

    private static func decodeLodgingOptions() throws {
        let data = Data(
            #"[{"candidate_id":"66666666-6666-6666-6666-666666666666","name":"Central Hotel","area":"Sapporo Station","address":"Sapporo","price_tier":2,"trip_start_date":"2026-09-25","trip_end_date":"2026-09-29","availability_note":"Confirm availability."}]"#.utf8
        )
        let options = try JSONDecoder().decode([LodgingOption].self, from: data)
        try require(options[0].name == "Central Hotel", "Lodging option names must decode")
        try require(options[0].priceTier == 2, "Lodging price tiers must decode")
    }

    private static func encodeLodgingSelection() throws {
        let request = LodgingSelectionRequest(
            travelerID: try uuid("22222222-2222-2222-2222-222222222222"),
            candidateID: try uuid("66666666-6666-6666-6666-666666666666")
        )
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
        guard let payload = object as? [String: Any] else {
            throw failure("Lodging selection must encode as a JSON object")
        }
        try require(payload["candidate_id"] as? String == "66666666-6666-6666-6666-666666666666", "Lodging selection must encode candidate_id")
    }

    private static func decodeCandidatePhoto() throws {
        let data = Data(
            #"{"provider":"google_places","photo_url":"https://example.com/place.jpg","width_px":1200,"height_px":800,"attributions":[{"display_name":"A Photographer","uri":"https://example.com/profile","photo_uri":null}]}"#.utf8
        )

        let response = try JSONDecoder().decode(CandidatePhoto.self, from: data)
        try require(response.provider == "google_places", "Photo provider must decode")
        try require(response.attributions[0].displayName == "A Photographer", "Photo attribution must decode")
    }

    private static func encodeVoteRequest() throws {
        let request = VoteRequest(
            travelerID: try uuid("22222222-2222-2222-2222-222222222222"),
            candidateID: try uuid("33333333-3333-3333-3333-333333333333"),
            signal: .like
        )
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
        guard let payload = object as? [String: Any] else {
            throw failure("Vote request must encode as a JSON object")
        }

        try require(
            payload["traveler_id"] as? String == "22222222-2222-2222-2222-222222222222",
            "Vote request must encode traveler_id"
        )
        try require(
            payload["candidate_id"] as? String == "33333333-3333-3333-3333-333333333333",
            "Vote request must encode candidate_id"
        )
        try require(payload["note_text"] == nil, "A plain like must omit note_text")
    }

    private static func encodeLikeWithNoteRequest() throws {
        let request = VoteRequest(
            travelerID: try uuid("22222222-2222-2222-2222-222222222222"),
            candidateID: try uuid("33333333-3333-3333-3333-333333333333"),
            signal: .likeWithNote,
            noteText: "Only if the weather is good"
        )
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
        guard let payload = object as? [String: Any] else {
            throw failure("Noted vote must encode as a JSON object")
        }
        try require(payload["signal"] as? String == "like_with_note", "Noted vote must use like_with_note")
        try require(payload["note_text"] as? String == "Only if the weather is good", "Noted vote must encode its text")
    }

    private static func decodeVoteResponse() throws {
        let data = Data(
            #"""
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "candidate_id": "33333333-3333-3333-3333-333333333333",
                "traveler_id": "22222222-2222-2222-2222-222222222222",
                "signal": "like",
                "note_text": null,
                "note_parsed": null
            }
            """#.utf8
        )

        let response = try JSONDecoder().decode(VoteResponse.self, from: data)
        try require(
            response.candidateID.uuidString == "33333333-3333-3333-3333-333333333333",
            "Vote response must decode candidate_id"
        )
    }

    private static func encodeShortlistEditRequest() throws {
        let request = ShortlistEditRequest(
            travelerID: try uuid("22222222-2222-2222-2222-222222222222"),
            selectedCandidateIDs: [try uuid("33333333-3333-3333-3333-333333333333")],
            mustGoCandidateIDs: [try uuid("33333333-3333-3333-3333-333333333333")]
        )
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
        guard let payload = object as? [String: Any] else {
            throw failure("Shortlist edit must encode as a JSON object")
        }
        try require((payload["must_go_candidate_ids"] as? [String])?.count == 1, "Shortlist edit must encode must-go ids")
    }

    private static func decodeShortlistState() throws {
        let data = Data(
            #"{"trip_id":"11111111-1111-1111-1111-111111111111","selected_candidate_ids":["33333333-3333-3333-3333-333333333333"],"must_go_candidate_ids":[],"wishlist_excluded_ids":[],"confirmed_by":["22222222-2222-2222-2222-222222222222"],"confirmed_at":"2026-09-01T12:00:00Z","confirmations_required":1,"traveler_count":1,"is_confirmed":true}"#.utf8
        )
        let response = try JSONDecoder().decode(ShortlistStateResponse.self, from: data)
        try require(response.isConfirmed, "Shortlist confirmation state must decode")
        try require(response.confirmationsRequired == 1, "Shortlist quorum must decode")
    }

    private static func encodePlanRequest() throws {
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(PlanRequest.standard))
        guard let payload = object as? [String: Any] else {
            throw failure("Plan request must encode as a JSON object")
        }

        try require(payload["day_start"] as? String == "08:00:00", "Plan request must encode day_start")
        try require(payload["day_end"] as? String == "21:00:00", "Plan request must encode day_end")
    }

    private static func decodePlanResponse() throws {
        let data = Data(
            #"""
            {
                "version_id": "55555555-5555-5555-5555-555555555555",
                "version_no": 1,
                "placed_stops": 1,
                "narrative": null
            }
            """#.utf8
        )

        let response = try JSONDecoder().decode(PlanResponse.self, from: data)
        try require(response.versionNo == 1, "Plan response must decode version_no")
    }

    private static func buildItineraryViewerQuery() throws {
        let travelerID = try uuid("22222222-2222-2222-2222-222222222222")
        let items = APIClient.itineraryQueryItems(travelerID: travelerID)

        try require(items.count == 1, "Itinerary requests need one viewer query item")
        try require(items[0].name == "traveler_id", "Itinerary requests must name traveler_id")
        try require(
            items[0].value == travelerID.uuidString,
            "Itinerary requests must carry the current traveler_id"
        )
    }

    private static func decodeItineraryResponse() throws {
        let data = Data(
            #"""
            {
                "version_id": "55555555-5555-5555-5555-555555555555",
                "version_no": 1,
                "status": "active",
                "days": [{
                    "day": 1,
                    "date": "2026-09-25",
                    "stops": [{
                        "candidate_id": "33333333-3333-3333-3333-333333333333",
                        "name": "Odori Park",
                        "area": "Sapporo",
                        "description": "An easy green pause between busier stops.",
                        "description_source": "Travel guides",
                        "start_time": "09:00:00",
                        "end_time": "10:00:00",
                        "transit_from_prev_min": 0,
                        "transit_from_prev_mode": null,
                        "source_badges": [{
                            "kind": "discovered",
                            "label": "Found on Google Maps",
                            "contributor_name": null
                        }]
                    }, {
                        "candidate_id": "77777777-7777-7777-7777-777777777777",
                        "name": "Ramen Yokocho",
                        "area": "Sapporo",
                        "description": "An alley of ramen counters.",
                        "description_source": "Google",
                        "start_time": "12:00:00",
                        "end_time": "13:15:00",
                        "transit_from_prev_min": 12,
                        "transit_from_prev_mode": "transit_transitous",
                        "meal_slot": "lunch",
                        "source_badges": [{
                            "kind": "trending",
                            "label": "Trending on TikTok, RedNote",
                            "contributor_name": null
                        }]
                    }]
                }],
                "narrative": "A relaxed first day.",
                "wishlist_not_placed": [{
                    "candidate_id": "66666666-6666-6666-6666-666666666666",
                    "name": "Museum",
                    "reason_code": "time_window",
                    "reason_text": "No compatible opening window."
                }]
            }
            """#.utf8
        )

        let response = try JSONDecoder().decode(ItineraryResponse.self, from: data)
        try require(response.days[0].stops[0].name == "Odori Park", "Itinerary stops must decode")
        try require(
            response.days[0].stops[0].descriptionSource == "Travel guides",
            "Itinerary description sources must decode"
        )
        try require(
            response.days[0].stops[0].mealLabel == nil,
            "A stop that is not a meal must carry no meal label"
        )
        try require(
            response.days[0].stops[1].mealLabel == "Lunch",
            "Itinerary meal slots must decode and read back capitalised"
        )
        try require(
            response.days[0].stops[1].transitLabel == "public transit",
            "Transitous legs must have a traveler-facing transit label"
        )
        try require(
            response.usesTransitous,
            "Transitous-backed itineraries must expose their attribution requirement"
        )
        try require(
            response.days[0].stops[0].sourceBadges[0].label == "Found on Google Maps",
            "An itinerary stop must say where the place came from"
        )
        try require(
            response.days[0].stops[1].sourceBadges[0].kind == "trending",
            "Buzz provenance must survive onto the itinerary"
        )
        try require(response.wishlistNotPlaced.count == 1, "Wishlist reasons must decode")
    }

    private static func encodeReplanDecision() throws {
        let request = ReplanDecisionRequest(
            travelerID: try uuid("22222222-2222-2222-2222-222222222222")
        )
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
        guard let payload = object as? [String: Any] else {
            throw failure("Replan decision must encode as a JSON object")
        }
        try require(
            payload["traveler_id"] as? String == "22222222-2222-2222-2222-222222222222",
            "Replan decisions must identify the traveler"
        )
    }

    private static func buildReplanWebSocketURL() throws {
        let tripID = try uuid("11111111-1111-1111-1111-111111111111")
        let travelerID = try uuid("22222222-2222-2222-2222-222222222222")
        guard let baseURL = URL(string: "http://localhost:8000") else {
            throw failure("Invalid local backend URL")
        }
        let url = try APIClient.replanWebSocketURL(
            baseURL: baseURL,
            tripID: tripID,
            travelerID: travelerID
        )
        try require(url.scheme == "ws", "Local replan delivery must use ws")
        try require(
            url.path == "/trips/\(tripID)/replans/ws",
            "Replan delivery must use the trip-scoped WebSocket endpoint"
        )
        try require(
            URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first?.value
                == travelerID.uuidString,
            "Replan delivery must identify the current traveler"
        )
    }

    private static func decodeReplanProposal() throws {
        let data = Data(
            #"""
            {
                "event_id": "77777777-7777-7777-7777-777777777777",
                "trip_id": "11111111-1111-1111-1111-111111111111",
                "trigger_type": "place_closed",
                "status": "pending",
                "current_version_id": "55555555-5555-5555-5555-555555555555",
                "proposed_version_id": "66666666-6666-6666-6666-666666666666",
                "trace": {
                    "trigger": {"type": "place_closed"},
                    "affected_nodes": [{
                        "node_id": "88888888-8888-8888-8888-888888888888",
                        "candidate_id": "33333333-3333-3333-3333-333333333333",
                        "classification": "movable"
                    }],
                    "alternatives_considered": [{
                        "candidate_id": "99999999-9999-9999-9999-999999999999",
                        "score": 0.75,
                        "chosen": true,
                        "reason": "0.8 km detour, fatigue 1, vote score 0.75",
                        "rejected_reason": null
                    }],
                    "downstream_changes": []
                },
                "diff": {
                    "added": [{
                        "candidate_id": "99999999-9999-9999-9999-999999999999",
                        "name": "Nearby museum",
                        "node_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        "day": 0,
                        "start_time": "11:00:00",
                        "end_time": "12:00:00"
                    }],
                    "removed": [{
                        "candidate_id": "33333333-3333-3333-3333-333333333333",
                        "name": "Closed stop",
                        "node_id": "88888888-8888-8888-8888-888888888888",
                        "day": 0,
                        "start_time": "11:00:00",
                        "end_time": "12:00:00"
                    }],
                    "moved": [],
                    "time_changed": []
                }
            }
            """#.utf8
        )

        let response = try JSONDecoder().decode(ReplanProposalResponse.self, from: data)
        try require(response.status == .pending, "A new replan must decode as pending")
        try require(response.diff.added[0].name == "Nearby museum", "Added stops need names")
        try require(
            response.trace.alternativesConsidered[0].reason?.contains("0.8 km") == true,
            "The approval screen needs the quantified rescue reason"
        )
    }

    private static func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
        guard condition() else { throw failure(message) }
    }

    private static func uuid(_ value: String) throws -> UUID {
        guard let uuid = UUID(uuidString: value) else {
            throw failure("Invalid test UUID: \(value)")
        }
        return uuid
    }

    private static func failure(_ message: String) -> NSError {
        NSError(domain: "SyncineraryAPIContractTests", code: 1, userInfo: [
            NSLocalizedDescriptionKey: message
        ])
    }
}
