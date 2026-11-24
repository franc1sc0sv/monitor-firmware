//! Lists every monitor, how it opened (standard / profiled / not compatible / no channel) and its input.
//! Read-only unless `--switch <index> <dp|hdmi>` is given; a switch is reverted after `--hold` seconds
//! (default 5), so a test never leaves the user on another computer.
//!
//! cargo run --example desk [-- --switch 1 dp --hold 5]

use std::process::ExitCode;
use std::sync::Arc;
use std::time::Duration;

use monitor_ddc::{Input, Link, Opened, SystemClock, open, system_bus};

const TIMEOUT: Duration = Duration::from_secs(10);

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let switch = args.iter().position(|a| a == "--switch").and_then(|i| {
        let index = args.get(i + 1)?.parse::<usize>().ok()?;
        let target = args.get(i + 2)?.parse::<Input>().ok()?;
        Some((index, target))
    });
    let hold = args
        .iter()
        .position(|a| a == "--hold")
        .and_then(|i| args.get(i + 1)?.parse::<u64>().ok())
        .unwrap_or(5);

    let bus = match system_bus() {
        Ok(b) => b,
        Err(e) => {
            eprintln!("no bus: {e}");
            return ExitCode::FAILURE;
        }
    };
    let monitors = match bus.monitors() {
        Ok(m) => m,
        Err(e) => {
            eprintln!("enumeration failed: {e}");
            return ExitCode::FAILURE;
        }
    };
    for (index, info) in monitors.iter().enumerate() {
        let id = info
            .id()
            .map_or_else(|| "?".into(), |i| i.as_str().to_owned());
        let link = Link::new(Arc::clone(&bus), Arc::new(SystemClock::new()), info.handle);
        match open(link, info) {
            Opened::Standard(m) => {
                let live = m.live();
                println!(
                    "[{index}] {id}: standard protocol {} input={:?} live={live:?}",
                    m.protocol(),
                    m.input()
                );
                if let Some((_, target)) = switch.filter(|(i, _)| *i == index) {
                    let back = m.input().ok().flatten();
                    println!(
                        "    switch -> {target}: {:?}",
                        m.switch_input(target, TIMEOUT)
                    );
                    std::thread::sleep(Duration::from_secs(hold));
                    if let Some(back) = back {
                        println!("    revert -> {back}: {:?}", m.switch_input(back, TIMEOUT));
                    }
                }
            }
            Opened::Profiled(mut m) => {
                println!(
                    "[{index}] {id}: profiled {} input={:?}",
                    m.profile().key,
                    m.input()
                );
                if let Some((_, target)) = switch.filter(|(i, _)| *i == index) {
                    let back = m.input().ok().flatten();
                    println!(
                        "    switch -> {target}: {:?}",
                        m.switch_input(target, TIMEOUT)
                    );
                    std::thread::sleep(Duration::from_secs(hold));
                    if let Some(back) = back {
                        println!("    revert -> {back}: {:?}", m.switch_input(back, TIMEOUT));
                    }
                }
            }
            Opened::NotCompatible(e) => println!("[{index}] {id}: not compatible ({e})"),
            Opened::NoChannel(e) => println!("[{index}] {id}: no channel ({e})"),
        }
    }
    ExitCode::SUCCESS
}
