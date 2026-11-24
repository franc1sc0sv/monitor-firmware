//! Hardware check of the desk API on the real monitors (Windows or macOS).
//!
//! desk status                           one scan, every monitor's state
//! desk watch <secs>                     scan every 500 ms, print every event with the time
//! desk switch <name> <dp|hdmi> [secs]   switch, then watch for `secs` (default 4)
//! desk power-off <name> [secs]          standby by command (34" only), then watch (default 8)
//!
//! `<name>` is a prefix of the EDID name, profile key or monitor id ("lc34", "g5"); it must match one
//! monitor only.

use std::process::ExitCode;
use std::sync::Arc;
use std::time::{Duration, Instant};

use monitor_ddc::{Desk, MonitorState, SystemClock, system_bus};

const TIMEOUT: Duration = Duration::from_secs(10);

fn line(state: &MonitorState) -> String {
    let status = state.status.map_or_else(
        || "status=?".to_owned(),
        |s| {
            format!(
                "input={} power={:?} signal={}",
                s.input.map_or("?", |i| i.as_str()),
                s.power,
                s.signal.map_or("?".to_owned(), |v| v.to_string())
            )
        },
    );
    format!(
        "{} [{}] kind={} presence={:?} off={} {} host_on={} shows_this_host={:?}",
        state.name,
        state.id,
        state.kind.unwrap_or(if state.not_compatible {
            "not-compatible"
        } else {
            "unchecked"
        }),
        state.presence,
        state.off,
        status,
        state.host_input.map_or("?", |i| i.as_str()),
        state.shows_this_host()
    )
}

fn watch(desk: &mut Desk, start: Instant, secs: u64) {
    let end = Instant::now() + Duration::from_secs(secs);
    while Instant::now() < end {
        let t = Instant::now();
        let result = desk.scan();
        let took = t.elapsed().as_secs_f64();
        if took > 2.0 {
            println!(
                "{:7.2}s SLOW scan took {took:.1}s",
                start.elapsed().as_secs_f64()
            );
        }
        match result {
            Ok(events) => {
                for e in events {
                    println!("{:7.2}s EVENT {e:?}", start.elapsed().as_secs_f64());
                }
            }
            Err(e) => println!("{:7.2}s scan error: {e}", start.elapsed().as_secs_f64()),
        }
        std::thread::sleep(Duration::from_millis(500));
    }
}

fn find(desk: &Desk, name: &str) -> Option<MonitorState> {
    // Prefix match only: "g5" must not match "LC34G55T".
    let n = name.to_ascii_lowercase();
    let mut hits: Vec<MonitorState> = desk
        .states()
        .into_iter()
        .filter(|s| {
            s.name.to_ascii_lowercase().starts_with(&n)
                || s.kind.is_some_and(|k| k.starts_with(&n))
                || s.id.as_str().starts_with(&n)
        })
        .collect();
    (hits.len() == 1).then(|| hits.remove(0))
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let bus = match system_bus() {
        Ok(b) => b,
        Err(e) => {
            eprintln!("no bus: {e}");
            return ExitCode::FAILURE;
        }
    };
    let start = Instant::now();
    let mut desk = Desk::new(bus, Arc::new(SystemClock::new()));
    match desk.scan() {
        Ok(events) => {
            for e in events {
                println!("{:7.2}s EVENT {e:?}", start.elapsed().as_secs_f64());
            }
        }
        Err(e) => {
            eprintln!("scan failed: {e}");
            return ExitCode::FAILURE;
        }
    }
    let arg = |i: usize| args.get(i).map(String::as_str);
    let secs = |i: usize, default: u64| arg(i).and_then(|s| s.parse().ok()).unwrap_or(default);
    match arg(0).unwrap_or("status") {
        "status" => {}
        "watch" => watch(&mut desk, start, secs(1, 30)),
        "switch" => {
            let (Some(name), Some(Ok(target))) = (arg(1), arg(2).map(str::parse)) else {
                eprintln!("usage: desk switch <name> <dp|hdmi> [secs]");
                return ExitCode::FAILURE;
            };
            let Some(state) = find(&desk, name) else {
                eprintln!("no monitor matches {name:?}");
                return ExitCode::FAILURE;
            };
            let t = Instant::now();
            let result = desk.switch(&state.id, target, TIMEOUT);
            println!(
                "{:7.2}s switch {} -> {target}: {result:?} in {:.2}s",
                start.elapsed().as_secs_f64(),
                state.name,
                t.elapsed().as_secs_f64()
            );
            watch(&mut desk, start, secs(3, 4));
        }
        "power-off" => {
            let Some(state) = arg(1).and_then(|n| find(&desk, n)) else {
                eprintln!("usage: desk power-off <name> [secs]");
                return ExitCode::FAILURE;
            };
            println!(
                "{:7.2}s power-off {}: {:?}",
                start.elapsed().as_secs_f64(),
                state.name,
                desk.power_off(&state.id)
            );
            // Watch the standby, then try to wake by command (Unsupported without protocol 3).
            watch(&mut desk, start, secs(2, 8));
            println!(
                "{:7.2}s power-on {}: {:?}",
                start.elapsed().as_secs_f64(),
                state.name,
                desk.power_on(&state.id)
            );
            watch(&mut desk, start, 4);
        }
        other => {
            eprintln!("unknown command {other:?}");
            return ExitCode::FAILURE;
        }
    }
    for s in desk.states() {
        println!("{:7.2}s STATE {}", start.elapsed().as_secs_f64(), line(&s));
    }
    ExitCode::SUCCESS
}
