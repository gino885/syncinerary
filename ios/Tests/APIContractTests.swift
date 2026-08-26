import Foundation

@main
enum APIContractTests {
    static func main() throws {
        try encodeTripCreateRequest()
        try decodeTripCreatedResponse()
        try decodeGatherResponse()
        try decodeCandidateCard()
        try encodeVoteRequest()
        try decodeVoteResponse()
        try encodePlanRequest()
        try decodePlanResponse()
        try decodeItineraryResponse()
        print("iOS API contract tests passed")
    }

    private static func encodeTripCreateRequest() throws {
        let request = TripCreateRequest(
            destination: "Hokkaido",
            startDate: "2026-09-25",
            endDate: "2026-09-29",
            creatorName: "Gino",
            creatorHomeCity: nil
        )
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
        guard let payload = object as? [String: Any] else {
            throw failure("Trip request must encode as a JSON object")
        }

        try require(payload["start_date"] as? String == "2026-09-25", "Trip request must encode start_date")
        try require(payload["creator_name"] as? String == "Gino", "Trip request must encode creator_name")
    }

    private static func decodeTripCreatedResponse() throws {
        let data = Data(
            #"""
            {
                "trip": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "destination": "Hokkaido",
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
    }

    private static func decodeGatherResponse() throws {
        let response = try JSONDecoder().decode(
            GatherResponse.self,
            from: Data(#"{"deck_size":35}"#.utf8)
        )
        try require(response.deckSize == 35, "Gather response must decode deck_size")
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
                "dietary_tags": []
            }
            """#.utf8
        )

        let response = try JSONDecoder().decode(CandidateCard.self, from: data)
        try require(response.nameCanonical == "Odori Park", "Candidate names must decode")
        try require(response.durationEstimateMin == 60, "Candidate durations must decode")
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
    }

    private static func decodeVoteResponse() throws {
        let data = Data(
            #"""
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "candidate_id": "33333333-3333-3333-3333-333333333333",
                "traveler_id": "22222222-2222-2222-2222-222222222222",
                "signal": "like"
            }
            """#.utf8
        )

        let response = try JSONDecoder().decode(VoteResponse.self, from: data)
        try require(
            response.candidateID.uuidString == "33333333-3333-3333-3333-333333333333",
            "Vote response must decode candidate_id"
        )
    }

    private static func encodePlanRequest() throws {
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(PlanRequest.standard))
        guard let payload = object as? [String: Any] else {
            throw failure("Plan request must encode as a JSON object")
        }

        try require(payload["day_start"] as? String == "08:00:00", "Plan request must encode day_start")
        try require(payload["day_end"] as? String == "20:00:00", "Plan request must encode day_end")
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
                        "start_time": "09:00:00",
                        "end_time": "10:00:00",
                        "transit_from_prev_min": 0,
                        "transit_from_prev_mode": null
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
        try require(response.wishlistNotPlaced.count == 1, "Wishlist reasons must decode")
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
