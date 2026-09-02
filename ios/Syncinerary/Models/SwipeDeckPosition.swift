import Foundation

struct SwipeDeckPosition: Hashable, Sendable {
    private(set) var index: Int

    init(index: Int = 0) {
        self.index = max(0, index)
    }

    mutating func advance(total: Int) {
        index = min(max(0, total), index + 1)
    }

    mutating func moveBack() {
        index = max(0, index - 1)
    }
}
