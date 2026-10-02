import SwiftUI

struct BookedHotelForm: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Bindable var model: LodgingViewModel

    var body: some View {
        Section("Already booked?") {
            if model.session.trip.cities.count > 1 {
                Picker("City", selection: $model.hotelCity) {
                    ForEach(model.session.trip.cities, id: \.self) { Text($0).tag($0) }
                }
            }
            if dynamicTypeSize.isAccessibilitySize {
                Text("Hotel name or Google Maps link")
                    .font(.headline)
                    .fixedSize(horizontal: false, vertical: true)
            }
            TextField("Hotel name or Google Maps link", text: $model.hotelQuery,
                prompt: Text(dynamicTypeSize.isAccessibilitySize ? "Name or link" : "Hotel name or Google Maps link")
                    .foregroundStyle(AppTheme.faded), axis: .vertical)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button("Find my hotel") { Task { await model.searchHotels() } }
                .disabled(model.isSearchingHotel || model.hotelQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            if model.isSearchingHotel { ProgressView() }
            ForEach(model.hotelMatches) { hotel in
                VStack(alignment: .leading, spacing: 8) {
                    Text(hotel.name).font(.headline)
                    if let address = hotel.address { Text(address).font(.subheadline).foregroundStyle(AppTheme.faded) }
                    Button("This is my booked hotel") { Task { await model.saveHotel(hotel) } }
                        .frame(minHeight: 44)
                }
                .padding(.vertical, 4)
            }
            if model.didSearchHotel && model.hotelMatches.isEmpty && !model.isSearchingHotel {
                Text("No hotel matched. Try its full name and check the city.")
                    .foregroundStyle(AppTheme.faded)
            }
        }
        .disabled(model.isSavingHotel)
        .onChange(of: model.hotelQuery) { model.clearHotelResults() }
        .onChange(of: model.hotelCity) { model.clearHotelResults() }
    }
}
