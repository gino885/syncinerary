import Foundation

enum PreferenceCatalog {
    static let interests = [
        PreferenceTag(value: "local food", title: "Local food"),
        PreferenceTag(value: "coffee", title: "Coffee"),
        PreferenceTag(value: "street food", title: "Street food"),
        PreferenceTag(value: "hidden gems", title: "Hidden gems"),
        PreferenceTag(value: "architecture", title: "Architecture"),
        PreferenceTag(value: "history", title: "History"),
        PreferenceTag(value: "museums", title: "Museums"),
        PreferenceTag(value: "art", title: "Art"),
        PreferenceTag(value: "nature", title: "Nature"),
        PreferenceTag(value: "hiking", title: "Hiking"),
        PreferenceTag(value: "gardens", title: "Gardens"),
        PreferenceTag(value: "hot springs", title: "Hot springs"),
        PreferenceTag(value: "photography", title: "Photography"),
        PreferenceTag(value: "shopping", title: "Shopping"),
        PreferenceTag(value: "nightlife", title: "Nightlife"),
        PreferenceTag(value: "anime", title: "Anime"),
        PreferenceTag(value: "design", title: "Design"),
        PreferenceTag(value: "music", title: "Music"),
        PreferenceTag(value: "markets", title: "Markets"),
        PreferenceTag(value: "family activities", title: "Family activities"),
        PreferenceTag(value: "slow travel", title: "Slow travel"),
        PreferenceTag(value: "day trips", title: "Day trips"),
    ]

    static let dietaryExcludes = [
        PreferenceTag(value: "seafood", title: "Seafood"),
        PreferenceTag(value: "shellfish", title: "Shellfish"),
        PreferenceTag(value: "meat", title: "Meat"),
        PreferenceTag(value: "pork", title: "Pork"),
        PreferenceTag(value: "beef", title: "Beef"),
        PreferenceTag(value: "peanuts", title: "Peanuts"),
        PreferenceTag(value: "tree nuts", title: "Tree nuts"),
        PreferenceTag(value: "dairy", title: "Dairy"),
        PreferenceTag(value: "eggs", title: "Eggs"),
        PreferenceTag(value: "gluten", title: "Gluten"),
        PreferenceTag(value: "alcohol", title: "Alcohol"),
    ]
}
