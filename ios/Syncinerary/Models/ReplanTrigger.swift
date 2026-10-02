enum ReplanTrigger: String, Decodable, Sendable {
    case reservationCancelled = "reservation_cancelled"
    case transitDelay = "transit_delay"
    case overslept
    case placeClosed = "place_closed"
    case weather
    case userRequest = "user_request"
    case other

    var label: String {
        switch self {
        case .reservationCancelled:
            String(localized: "Reservation cancelled")
        case .transitDelay:
            String(localized: "Transit delay")
        case .overslept:
            String(localized: "Late start")
        case .placeClosed:
            String(localized: "Place closed")
        case .weather:
            String(localized: "Weather change")
        case .userRequest:
            String(localized: "Your trip changes")
        case .other:
            String(localized: "Trip change")
        }
    }
}
