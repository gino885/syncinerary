enum ReplanTrigger: String, Decodable, Sendable {
    case reservationCancelled = "reservation_cancelled"
    case transitDelay = "transit_delay"
    case overslept
    case placeClosed = "place_closed"
    case weather
    case other

    var label: String {
        switch self {
        case .reservationCancelled:
            "Reservation cancelled"
        case .transitDelay:
            "Transit delay"
        case .overslept:
            "Late start"
        case .placeClosed:
            "Place closed"
        case .weather:
            "Weather change"
        case .other:
            "Trip change"
        }
    }
}
