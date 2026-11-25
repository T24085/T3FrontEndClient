-- Hold out a deterministic subset of native player starts from adaptive CTF training.
return function(starts, held_out, round)
    for team=1,2 do
        local ordered = starts[team]
        table.sort(ordered,function(a,b) return a:GetFullName() < b:GetFullName() end)
        if #ordered > 1 then
            local boundary = math.floor(#ordered*.75)
            local first, last = held_out and boundary+1 or 1, held_out and #ordered or boundary
            local pool, length = {}, last-first+1
            for slot=1,length do pool[slot] = ordered[first+(slot+round-2)%length] end
            starts[team] = pool
        elseif held_out then
            error('field_benchmark_insufficient_native_starts|team='..team)
        end
    end
end
