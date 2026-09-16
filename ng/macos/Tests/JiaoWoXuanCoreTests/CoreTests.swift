import Foundation
import XCTest
@testable import JiaoWoXuanCore

final class ModelDecodingTests: XCTestCase {
    func testGroupConflictsKeepRawDictionaryKeys() throws {
        let json = """
        {"name":"物理","is_pe":false,"priority":["A1_b2","held"],"held":"held","held_label":"大学物理 - 02",
         "watched_count":1,"fatal":false,"members":[],
         "conflicts":{"A1_b2":{"status":"conflict","with":"高数 - 01","detail":"周一 第2节 (第1周)"}},
         "conflict_count":1}
        """
        let group = try JSONDecoder().decode(PriorityGroup.self, from: Data(json.utf8))
        XCTAssertEqual(group.conflicts["A1_b2"]?.status, .conflict)
        XCTAssertEqual(group.conflicts["A1_b2"]?.note, "与已选 高数 - 01 冲突：周一 第2节 (第1周)")
        XCTAssertEqual(group.plan, PriorityGroup.Plan(name: "物理", isPe: false, priority: ["A1_b2", "held"]))
    }

    func testRatingZeroScoreIsKept() throws {
        let json = #"{"status":"rated","score":0,"count":0,"teacher":null,"semester":null,"updated_at":null,"message":null}"#
        let rating = try JSONDecoder().decode(CourseRating.self, from: Data(json.utf8))
        XCTAssertEqual(rating.score, 0)
        XCTAssertEqual(rating.count, 0)
        XCTAssertEqual(rating.scoreText, "0.0")
    }
}

final class CourseFilterTests: XCTestCase {
    private func course(_ id: String, _ title: String, score: Double? = nil, open: Bool = false, group: String? = nil) -> CourseRow {
        CourseRow(
            jxbId: id, title: title, className: "01", summary: "", detail: "", teachers: "", schedule: [],
            locations: [], searchText: "\(title) \(id)".lowercased(), seatText: "-",
            availability: open ? .open : .full, availabilityText: "", group: group, chosen: false, category: "主修",
            ratingText: "", rating: CourseRating(status: score == nil ? .unknown : .rated, score: score),
            kch: nil, sksj: nil
        )
    }

    func testRatingSortPutsUnratedLast() {
        var filter = CourseFilter()
        filter.sort = .rating
        let result = filter.apply(to: [course("a", "甲"), course("b", "乙", score: 3), course("c", "丙", score: 4.5)])
        XCTAssertEqual(result.map(\.jxbId), ["c", "b", "a"])
    }

    func testFiltersCombine() {
        var filter = CourseFilter()
        filter.onlyOpen = true
        filter.onlyUnassigned = true
        filter.query = "物理"
        let result = filter.apply(to: [
            course("a", "大学物理", open: true),
            course("b", "大学物理", open: true, group: "g"),
            course("c", "大学物理"),
            course("d", "高等数学", open: true),
        ])
        XCTAssertEqual(result.map(\.jxbId), ["a"])
    }
}

extension CourseRating {
    init(status: RatingStatus, score: Double?) {
        self.init(status: status, score: score, count: nil, teacher: nil, semester: nil, updatedAt: nil, message: nil)
    }
}

final class BackendClientTests: XCTestCase {
    /// 真正起一个 ng_service(需要仓库里的 conda Python),走一次 hello/snapshot/错误路径。
    func testRoundTripAgainstRealService() async throws {
        let repo = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        guard FileManager.default.fileExists(atPath: repo.appendingPathComponent("ng_service.py").path) else {
            throw XCTSkip("仓库外运行")
        }
        let data = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: data, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: data) }

        var env = ProcessInfo.processInfo.environment
        env["SJTU_MONITOR_ROOT"] = repo.path
        env["SJTU_MONITOR_DATA_DIR"] = data.path
        let launch: BackendLaunch
        do {
            launch = try BackendLocator.resolve(environment: env)
        } catch {
            throw XCTSkip("没有可用的 Python: \(error)")
        }
        var launchEnv = launch.environment
        launchEnv["SJTU_MONITOR_DATA_DIR"] = data.path
        let configured = BackendLaunch(executable: launch.executable, arguments: launch.arguments,
                                       environment: launchEnv, workingDirectory: launch.workingDirectory,
                                       description: launch.description)

        let ready = expectation(description: "ready")
        let client = BackendClient(launch: configured) { event in
            if case .ready = event { ready.fulfill() }
        }
        try client.start()
        await fulfillment(of: [ready], timeout: 30)

        let hello = try await client.call("hello", as: HelloInfo.self)
        XCTAssertEqual(hello.protocolVersion, 1)
        XCTAssertEqual(URL(fileURLWithPath: hello.dataDir).standardizedFileURL.path,
                       data.standardizedFileURL.path)

        let snapshot = try await client.call("snapshot", as: Snapshot.self)
        XCTAssertFalse(snapshot.onboarding.completed)
        XCTAssertTrue(snapshot.courses.isEmpty)

        do {
            _ = try await client.call("no.such.method", as: OkResult.self)
            XCTFail("应当报错")
        } catch let error as BackendError {
            XCTAssertEqual(error.code, "method_not_found")
        }
        client.shutdown()
        XCTAssertFalse(client.isRunning)
    }
}

final class RealSnapshotTests: XCTestCase {
    /// NG_SNAPSHOT_JSON 指向一份 ng_service snapshot 的输出时,校验真实数据能完整解码。
    func testDecodesRealSnapshotWhenProvided() throws {
        guard let path = ProcessInfo.processInfo.environment["NG_SNAPSHOT_JSON"] else {
            throw XCTSkip("未提供 NG_SNAPSHOT_JSON")
        }
        let snapshot = try JSONDecoder().decode(Snapshot.self, from: Data(contentsOf: URL(fileURLWithPath: path)))
        XCTAssertFalse(snapshot.courses.isEmpty)
        var filter = CourseFilter()
        filter.sort = .rating
        XCTAssertEqual(filter.apply(to: snapshot.courses).count, snapshot.courses.count)
    }
}
