enum HokkaidoCity: String, CaseIterable, Identifiable, Sendable {
    case sapporo = "Sapporo"
    case otaru = "Otaru"
    case hakodate = "Hakodate"
    case asahikawa = "Asahikawa"
    case kushiro = "Kushiro"

    var id: Self { self }
}
